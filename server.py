"""
IS436 Group 3 - Multi-client chat server.

Usage:
    python server.py <port> [--host HOST]

    <port>   TCP port to listen on, a whole number from 1025 to 65535
    --host   address to listen on (default 127.0.0.1; use 0.0.0.0 for other machines)

Why the server uses threads
---------------------------
A chat server spends its life WAITING for three different things:
    1. accept()  - waiting for a new client to connect
    2. recv()    - waiting for a connected client to send something
    3. input()   - waiting for the operator to type at the server console
Each of these calls BLOCKS: the thread that calls it freezes on that line
until something happens. If one thread did all three, waiting on one would
freeze the other two. So each waiting job gets its own thread:

    MAIN THREAD            the accept loop (exactly one)
    CLIENT HANDLER THREAD  one per connected client, loops on recv()
    CONSOLE THREAD         one, loops on input() for the server operator

Shared state and locks
----------------------
Several threads read and change the same data, so it is protected by locks:
    clients / next_id   -> clients_lock   (who is connected, next chat ID)
    each client socket  -> client.send_lock (one message at a time per socket)
    the SQLite database -> db_lock
    the chat log file   -> a lock inside storage.logger.ChatLogger
    console printing    -> print_lock (so lines from different threads don't mix)
shutdown_event (a threading.Event) tells every loop that the server is stopping.

Rule: never hold a lock while doing slow network I/O. broadcast() copies the
client list while holding clients_lock, RELEASES the lock, and only then sends.
"""
import argparse
import socket
import sqlite3
import sys
import threading

from common import config, protocol
from common.protocol import SERVER_NAME
from db import database
from storage.logger import ChatLogger

DEFAULT_ROOM = "general"


class Client:
    """Everything the server knows about one connected client."""

    def __init__(self, chat_id, conn, addr):
        self.chat_id = chat_id      # unique ID shown in messages, e.g. "Client-3"
        self.conn = conn            # the client's TCP socket
        self.addr = addr            # (ip, port) of the client
        self.username = None        # set when the client sends its "hello" message
        self.user_id = None         # USERS.user_id in the database
        self.session_id = None      # CONNECTION_SESSIONS.session_id in the database

        # Several threads may send to this client at the same moment (for
        # example two other clients chatting at once). sendall() may need
        # several system calls for one message, so without this lock the
        # bytes of two messages could interleave and corrupt the stream.
        self.send_lock = threading.Lock()

    @property
    def label(self):
        """How the client is shown to others, e.g. 'Alice (Client-3)'."""
        if self.username is None or self.username == self.chat_id:
            return self.chat_id
        return f"{self.username} ({self.chat_id})"


# ===========================================================================
# Shared state (used by many threads - see the locks next to each item)
# ===========================================================================
clients = {}                        # chat_id -> Client, for everyone connected right now
next_id = 0                         # last chat number handed out; only changed inside clients_lock
clients_lock = threading.Lock()     # protects `clients` and `next_id`

shutdown_event = threading.Event()  # set() once = "the server is stopping", seen by every loop
print_lock = threading.Lock()       # keeps lines printed by different threads from mixing

db_conn = None                      # one SQLite connection, shared ...
db_lock = threading.Lock()          # ... so only one thread may use it at a time
server_user_id = None               # USERS row used as the sender of console messages
room_id = None                      # CHAT_ROOMS row of the "general" room

chat_log = None                     # storage.logger.ChatLogger (has its own lock)
handler_threads = []                # client threads, so shutdown can wait for them


# ===========================================================================
# Small helpers
# ===========================================================================

def console_print(text):
    """Print a line on the server console, one thread at a time."""
    if text:
        with print_lock:
            print(text, flush=True)


def db_run(func, *args):
    """
    Call one db.database helper while holding db_lock.

    A database problem is reported on the console but never crashes the chat:
    the chat keeps working even if, for example, the .db file is locked.
    """
    with db_lock:
        if db_conn is None:         # database already closed during shutdown
            return None
        try:
            return func(db_conn, *args)
        except sqlite3.Error as error:
            console_print(f"[database] {error}")
            return None


def error_message(text):
    return {"type": "error", "text": text, "timestamp": protocol.now_timestamp()}


def send_to(client, message):
    """Send one message to one client. Returns False if the socket is dead."""
    data = protocol.encode(message)
    try:
        with client.send_lock:
            client.conn.sendall(data)   # sendall() loops until EVERY byte is sent (send() might not)
        return True
    except OSError:
        return False


def broadcast(message, exclude=None):
    """
    Send a message to every connected client (except `exclude`, if given).

    Step 1: copy the list of clients while holding clients_lock.
    Step 2: release the lock, THEN send. Sending can be slow (a client with a
            full network buffer makes sendall() wait); if we held the lock
            the whole time, nobody else could join or leave meanwhile.
    Step 3: any client whose send failed is removed and its socket closed.
            Closing the socket wakes its handler thread, which then runs its
            normal cleanup and announces that the client left.
    """
    with clients_lock:
        targets = [client for client in clients.values() if client is not exclude]

    failed = [client for client in targets if not send_to(client, message)]

    if failed:
        with clients_lock:
            for client in failed:
                clients.pop(client.chat_id, None)
        for client in failed:
            protocol.close_socket(client.conn)


def publish(message):
    """Log an event, show it on the server console and send it to every client."""
    chat_log.log(message)
    console_print(protocol.format_message(message))
    broadcast(message)


def check_text(text):
    """Return a friendly error if a chat message breaks the rules, otherwise None."""
    if not text:
        return "Empty messages are not sent - type something first."
    if len(text) > config.MAX_MESSAGE_LENGTH:
        return (f"Your message is {len(text)} characters long; the limit is "
                f"{config.MAX_MESSAGE_LENGTH}. It was not sent.")
    return None


def clean_username(raw_name, fallback):
    """Tidy up a requested username (collapse spaces, cut to max length)."""
    name = " ".join(str(raw_name or "").split())
    return name[:config.MAX_USERNAME_LENGTH] if name else fallback


# ===========================================================================
# Joining, chatting, leaving
# ===========================================================================

def send_welcome(client):
    """Greet a new client with its chat ID and how to exit, then send recent history."""
    with clients_lock:
        online = len(clients)
    send_to(client, {
        "type": "welcome",
        "chat_id": client.chat_id,
        "text": (f"Welcome to the IS436 G3 chat server! You are {client.chat_id}. "
                 f"{online} user(s) online. Type '{config.EXIT_KEYWORD}' to leave the chat."),
        "timestamp": protocol.now_timestamp(),
    })

    # Chat history on join: the last few messages from the chat log.
    history = chat_log.recent_messages()
    if history:
        send_to(client, {"type": "history", "messages": history})


def join_chat(client, requested_name):
    """Give the client its username, record it in the database and announce it to everyone."""
    client.username = clean_username(requested_name, client.chat_id)
    timestamp = protocol.now_timestamp()

    # USERS.username is the unique (AK) key, stored lower-case; display_name keeps the user's spelling.
    client.user_id = db_run(database.get_or_create_user, client.username.lower(), client.username, timestamp)
    if client.user_id:
        db_run(database.join_room, room_id, client.user_id)
        db_run(database.set_user_status, client.user_id, "online")
        client.session_id = db_run(database.open_session, client.user_id,
                                   f"{client.addr[0]}:{client.addr[1]}", timestamp)

    publish({
        "type": "join",
        "chat_id": client.chat_id,
        "username": client.username,
        "text": f"{client.label} joined the chat. Say hi!",
        "timestamp": timestamp,
    })


def handle_message(client, message):
    """
    Act on one complete message from a client.

    Returns True to keep the connection open, False if the client wants to leave.
    """
    kind = message.get("type")

    # Clients are expected to send "hello" first. A client that skips it
    # (e.g. raw telnet) joins automatically, using its chat ID as its name.
    if client.username is None and kind in ("chat", "typing"):
        join_chat(client, None)

    if kind == "hello":
        if client.username is None:         # ignore a second hello
            join_chat(client, message.get("username"))
        return True

    if kind == "exit":
        return False

    if kind == "typing":
        # "Alice is typing..." goes to everyone EXCEPT Alice. Not logged.
        broadcast({
            "type": "typing",
            "chat_id": client.chat_id,
            "username": client.username,
            "is_typing": bool(message.get("is_typing")),
        }, exclude=client)
        return True

    if kind == "chat":
        text = str(message.get("text", "")).strip()
        if text.lower() == config.EXIT_KEYWORD:     # typing "exit" also works with raw clients
            return False

        problem = check_text(text)
        if problem:
            send_to(client, error_message(problem))  # tell ONLY the sender, nobody else
            return True

        # The SERVER stamps the time, so everyone sees the same timestamp.
        timestamp = protocol.now_timestamp()
        if client.user_id:
            db_run(database.save_message, room_id, client.user_id, text, timestamp)
        publish({
            "type": "chat",
            "sender": client.chat_id,
            "username": client.username,
            "text": text,
            "timestamp": timestamp,
        })
        return True

    send_to(client, error_message(f"Unknown message type: {kind!r}"))
    return True


def handle_client(client):
    """
    CLIENT HANDLER THREAD - one of these runs for every connected client.

    Loops on recv() until the client leaves, disconnects or the server stops.
    The try/finally guarantees cleanup_client() runs no matter how the loop ends.
    """
    buffer = b""                    # bytes received but not processed yet (may hold half a message)
    reason = "disconnected"         # how the client left, used in the "left" announcement
    try:
        send_welcome(client)

        while not shutdown_event.is_set():
            try:
                # BLOCKS until the client sends something, disconnects,
                # or another thread closes this socket (server shutdown).
                data = client.conn.recv(config.BUFFER_SIZE)
            except OSError:
                # ConnectionResetError / ConnectionAbortedError (both OSErrors):
                # the client vanished without closing properly, e.g. its program
                # was killed. Also raised if our own shutdown closed the socket.
                reason = "lost connection"
                break

            if not data:
                # recv() returning b"" means the other side closed the connection cleanly.
                break

            # TCP is a stream: add the new bytes to the buffer and process only
            # the complete lines. Any partial line stays in the buffer.
            buffer += data
            messages, buffer = protocol.split_lines(buffer)

            if len(buffer) > config.MAX_LINE_BYTES:
                # A "message" this big with no newline is not normal - drop it
                # so one client cannot make the server use unlimited memory.
                buffer = b""
                send_to(client, error_message("That message was far too large and was dropped."))

            keep_going = True
            for message in messages:
                if not handle_message(client, message):
                    reason = "left the chat"
                    keep_going = False
                    break
            if not keep_going:
                break
    except Exception as error:      # a bug while handling one client must not kill the server
        console_print(f"[error] {client.chat_id}: {error!r}")
    finally:
        # ALWAYS runs: on "exit", clean disconnect, crash, or server shutdown.
        cleanup_client(client, reason)


def cleanup_client(client, reason):
    """Remove a client from the registry, close its socket, log and announce that it left."""
    # 1. Remove from the shared registry (under the lock).
    with clients_lock:
        clients.pop(client.chat_id, None)
        same_user_still_online = any(other.user_id == client.user_id for other in clients.values())

    # 2. Close the socket (harmless if it is already closed).
    protocol.close_socket(client.conn)

    # 3. Record the disconnect time in the database.
    timestamp = protocol.now_timestamp()
    if client.session_id:
        db_run(database.close_session, client.session_id, timestamp)
    if client.user_id and not same_user_still_online:
        db_run(database.set_user_status, client.user_id, "offline")

    # During a server shutdown everyone has already been told; don't announce each leave.
    if shutdown_event.is_set():
        return

    if client.username is None:
        console_print(f"[-] {client.chat_id} disconnected before choosing a name.")
        return

    # 4. Log the disconnect and tell everyone else.
    publish({
        "type": "leave",
        "chat_id": client.chat_id,
        "username": client.username,
        "text": f"{client.label} {reason}.",
        "timestamp": timestamp,
    })


# ===========================================================================
# CONSOLE THREAD - lets the server operator chat and run commands
# ===========================================================================

def console_loop():
    """Loop on input(): broadcast typed text as "Server", or run a command."""
    console_print(f"Type a message and press Enter to chat. Commands: /users, /help, "
                  f"{' or '.join(config.SERVER_QUIT_COMMANDS)} to stop the server.")
    while not shutdown_event.is_set():
        try:
            line = input()          # BLOCKS until the operator presses Enter
        except (EOFError, KeyboardInterrupt):
            # No console available (stdin closed). The server keeps running;
            # it can still be stopped with Ctrl+C in the main thread.
            return
        if shutdown_event.is_set():
            return

        text = line.strip()
        command = text.lower()
        if not text:
            continue

        if command in config.SERVER_QUIT_COMMANDS:
            console_print("Shutdown requested from the console...")
            shutdown_event.set()    # the accept loop notices within ACCEPT_TIMEOUT seconds
            return

        if command == "/users":
            with clients_lock:
                labels = [client.label for client in clients.values()]
            console_print(f"{len(labels)} connected: " + (", ".join(labels) if labels else "nobody"))
            continue

        if command == "/help":
            console_print("Just type to chat with every client. /users lists who is connected. "
                          f"{' or '.join(config.SERVER_QUIT_COMMANDS)} stops the server.")
            continue

        problem = check_text(text)
        if problem:
            console_print(f"[!] {problem}")
            continue

        timestamp = protocol.now_timestamp()
        db_run(database.save_message, room_id, server_user_id, text, timestamp)
        publish({
            "type": "chat",
            "sender": SERVER_NAME,
            "username": SERVER_NAME,
            "text": text,
            "timestamp": timestamp,
        })


# ===========================================================================
# MAIN THREAD - start-up, accept loop, graceful shutdown
# ===========================================================================

def accept_loop(server_socket):
    """Wait for new clients and start one handler thread for each."""
    global next_id
    while not shutdown_event.is_set():
        try:
            # Because of settimeout(ACCEPT_TIMEOUT), accept() gives up after
            # about one second. That lets this loop re-check shutdown_event;
            # without it, accept() would wait forever and shutdown would hang.
            conn, addr = server_socket.accept()
        except socket.timeout:
            continue                # nobody connected this second; check shutdown_event again
        except OSError:
            break                   # the listening socket was closed

        # Sockets returned by accept() may inherit the timeout; clients need normal blocking recv().
        conn.settimeout(None)

        # Assign the chat ID and register the client in ONE locked step, so
        # two clients connecting at the same moment can never get the same ID.
        with clients_lock:
            next_id += 1
            client = Client(f"Client-{next_id}", conn, addr)
            clients[client.chat_id] = client

        console_print(f"[+] {client.chat_id} connected from {addr[0]}:{addr[1]}")

        # daemon=True: if something goes wrong, these threads can never keep
        # the program alive after the main thread finishes.
        thread = threading.Thread(target=handle_client, args=(client,),
                                  name=f"handler-{client.chat_id}", daemon=True)
        thread.start()

        # Remember live handler threads so shutdown can wait for them.
        handler_threads[:] = [t for t in handler_threads if t.is_alive()]
        handler_threads.append(thread)


def shutdown_server(server_socket):
    """Graceful shutdown: tell clients, close every socket, wait, flush the log and database."""
    global db_conn

    # 1. Tell every loop (accept, handlers, console) that we are stopping.
    shutdown_event.set()

    # 2. Say goodbye to the clients while their sockets are still open.
    console_print("Shutting down: notifying clients...")
    broadcast({"type": "shutdown", "text": "The server is shutting down. Goodbye!",
               "timestamp": protocol.now_timestamp()})

    # 3. Close every client socket. This wakes each handler thread out of
    #    recv(), so it can run its finally-block and end.
    with clients_lock:
        remaining = list(clients.values())
        clients.clear()
    for client in remaining:
        protocol.close_socket(client.conn)

    # 4. Close the listening socket so no new clients can connect.
    try:
        server_socket.close()
    except OSError:
        pass

    # 5. Wait (briefly) for handler threads to finish their cleanup.
    for thread in handler_threads:
        thread.join(timeout=2.0)

    # 6. Flush and close the chat log; mark open sessions as ended in the database.
    chat_log.log({"type": "system", "text": "Server stopped.", "timestamp": protocol.now_timestamp()})
    chat_log.close()
    with db_lock:
        if db_conn is not None:
            try:
                database.close_open_sessions(db_conn, protocol.now_timestamp())
                database.set_all_offline(db_conn)
                db_conn.close()
            except sqlite3.Error as error:
                print(f"[database] {error}")
            db_conn = None

    console_print("Server stopped. Goodbye!")
    # The console thread may still be blocked in input(); it is a daemon
    # thread, so it does not stop the program from exiting.


def parse_args():
    parser = argparse.ArgumentParser(description="IS436 G3 multi-client chat server.")
    parser.add_argument("port", help=f"TCP port to listen on ({config.MIN_PORT}-{config.MAX_PORT})")
    parser.add_argument("--host", default=config.HOST,
                        help=f"address to listen on (default {config.HOST}; use 0.0.0.0 for other machines)")
    return parser.parse_args()


def setup_storage():
    """Open the chat log and the database, and make sure the 'Server' user and 'general' room exist."""
    global chat_log, db_conn, server_user_id, room_id
    chat_log = ChatLogger(config.LOG_FILE, config.HISTORY_SIZE)

    database.init_db()
    db_conn = database.get_connection()
    server_user_id = database.get_or_create_user(db_conn, SERVER_NAME.lower(), SERVER_NAME)
    room_id = database.get_or_create_room(db_conn, DEFAULT_ROOM, server_user_id)


def main():
    # Never crash just because a message contains a character the console can't show.
    sys.stdout.reconfigure(errors="replace")

    args = parse_args()

    # Validate the port: a whole number from 1025 to 65535, else a clear error and exit code 1.
    try:
        port = config.parse_port(args.port)
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        print("Usage: python server.py <port>   e.g. python server.py 5050", file=sys.stderr)
        sys.exit(1)

    # Create the listening TCP socket.
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # SO_REUSEADDR lets us restart the server on the same port right away,
    # instead of waiting for the OS to release it.
    # Windows is different: there SO_REUSEADDR would let a SECOND server
    # silently share a port that is already in use. Windows does not need it
    # for quick restarts, so we use SO_EXCLUSIVEADDRUSE there instead, which
    # makes bind() fail with a clear error if the port is taken.
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):      # only exists on Windows
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_socket.bind((args.host, port))
    except OSError as error:
        print(f"Error: cannot listen on {args.host}:{port} ({error.strerror or error}). "
              f"Is another program already using that port?", file=sys.stderr)
        server_socket.close()
        sys.exit(1)
    server_socket.listen()
    server_socket.settimeout(config.ACCEPT_TIMEOUT)   # see accept_loop() for why

    setup_storage()
    chat_log.log({"type": "system", "text": f"Server started on {args.host}:{port}.",
                  "timestamp": protocol.now_timestamp()})

    console_print(f"Chat server listening on {args.host}:{port}")
    console_print(f"Chat log: {config.LOG_FILE}")
    console_print("Press Ctrl+C or type /quit to stop the server.")

    # CONSOLE THREAD: daemon, because input() cannot be interrupted - we do
    # not want a thread stuck in input() to keep the program running at exit.
    threading.Thread(target=console_loop, name="console", daemon=True).start()

    try:
        accept_loop(server_socket)
    except KeyboardInterrupt:
        # Ctrl+C lands here (in the main thread) and takes the same graceful path.
        console_print("\nCtrl+C pressed.")
    finally:
        shutdown_server(server_socket)


if __name__ == "__main__":
    main()
