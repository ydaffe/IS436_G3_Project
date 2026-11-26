"""
IS436 Group 3 - Command-line chat client.

Usage:
    python client.py <port> [--host HOST] [--name NAME]

    <port>   port the server is listening on (1025-65535)
    --host   server address (default 127.0.0.1)
    --name   your username (if left out, you are asked for one)

Threads
-------
    MAIN THREAD      reads what you type with input() and sends it
    RECEIVER THREAD  (daemon) loops on recv() and prints incoming messages
Both wait (block) on different things - the keyboard and the network - so
each needs its own thread; otherwise you could not receive while typing.
"""
import argparse
import sys
import threading

from common import config, protocol


def receive_loop(sock, leaving, disconnected):
    """
    RECEIVER THREAD: print every message the server sends.

    leaving      - Event set by the main thread when WE chose to exit
    disconnected - Event this thread sets when the connection is gone
    """
    buffer = b""
    try:
        while True:
            try:
                data = sock.recv(config.BUFFER_SIZE)    # BLOCKS until the server sends something
            except OSError:
                break                       # socket closed (we are exiting) or connection reset
            if not data:
                break                       # b"" = the server closed the connection

            # Same buffering as the server: keep partial lines until they are complete.
            buffer += data
            messages, buffer = protocol.split_lines(buffer)
            for message in messages:
                text = protocol.format_message(message)
                if text:
                    print(text, flush=True)
    finally:
        disconnected.set()
        if not leaving.is_set():
            # The server went away first. input() in the main thread cannot be
            # interrupted from here, so ask the user to press Enter.
            print("\n*** Disconnected from the server. Press Enter to exit.", flush=True)


def send(sock, message):
    """Send one message. Returns False if the connection is broken."""
    try:
        sock.sendall(protocol.encode(message))
        return True
    except OSError:
        return False


def ask_username():
    """Ask for a username until it is short enough (blank = use the chat ID)."""
    while True:
        name = input("Enter a username (or just press Enter to use your chat ID): ").strip()
        if len(name) <= config.MAX_USERNAME_LENGTH:
            return name
        print(f"Please use at most {config.MAX_USERNAME_LENGTH} characters.")


def parse_args():
    parser = argparse.ArgumentParser(description="IS436 G3 chat client (command line).")
    parser.add_argument("port", help=f"server port ({config.MIN_PORT}-{config.MAX_PORT})")
    parser.add_argument("--host", default=config.HOST, help=f"server address (default {config.HOST})")
    parser.add_argument("--name", help="your username")
    return parser.parse_args()


def main():
    sys.stdout.reconfigure(errors="replace")   # never crash on characters the console can't show
    args = parse_args()

    try:
        port = config.parse_port(args.port)
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        print("Usage: python client.py <port>   e.g. python client.py 5050", file=sys.stderr)
        sys.exit(1)

    try:
        name = args.name if args.name is not None else ask_username()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return

    # Connect - a refused connection prints a friendly message instead of a traceback.
    try:
        sock = protocol.connect_to_server(args.host, port)
    except ConnectionError as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print(f" Connected to the chat server at {args.host}:{port}")
    print(" Type a message and press Enter to send it.")
    print(f" Type '{config.EXIT_KEYWORD}' (or press Ctrl+C) to leave the chat.")
    print("=" * 60)

    # Tell the server who we are (it answers with a welcome message and our chat ID).
    send(sock, {"type": "hello", "username": name})

    leaving = threading.Event()
    disconnected = threading.Event()

    # RECEIVER THREAD: daemon, so it can never keep the program alive after we exit.
    receiver = threading.Thread(target=receive_loop, args=(sock, leaving, disconnected),
                                name="receiver", daemon=True)
    receiver.start()

    try:
        while not disconnected.is_set():
            try:
                line = input()              # BLOCKS until Enter is pressed
            except (EOFError, KeyboardInterrupt):
                line = config.EXIT_KEYWORD  # Ctrl+C / Ctrl+Z behave like typing "exit"

            if disconnected.is_set():       # server left while we were waiting for input
                break
            if line == "":
                continue                    # just Enter: ignore (the server rejects blank text anyway)

            if line.strip().lower() == config.EXIT_KEYWORD:
                leaving.set()               # so the receiver doesn't report it as a server disconnect
                send(sock, {"type": "exit"})
                break

            if not send(sock, {"type": "chat", "text": line}):
                print("*** Could not send - the connection to the server was lost.")
                break
    finally:
        # Graceful shutdown of the client: close the socket (this also wakes
        # the receiver thread out of recv()), then give it a moment to finish.
        leaving.set()
        protocol.close_socket(sock)
        receiver.join(timeout=1.0)
        print("You have left the chat. Goodbye!")


if __name__ == "__main__":
    main()
