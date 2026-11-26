"""
Message protocol shared by the server and every client.

Wire format: newline-delimited JSON (also called "JSON Lines")
---------------------------------------------------------------
* Every message is ONE JSON object followed by a single newline (b"\\n").
* json.dumps() turns any newline inside a message's text into the two
  characters "\\n", so a real newline byte on the wire ALWAYS means
  "end of this message".

Why we need a buffer
--------------------
TCP is a byte STREAM, not a list of separate messages. One recv() call may
return half a message, exactly one message, or several messages glued
together. So the receiver keeps a buffer, adds every recv() result to the end
of it, and only processes the COMPLETE lines (see split_lines() below).
Whatever is left after the last newline stays in the buffer until the rest of
it arrives.

Message types
-------------
client -> server
    hello    {"type": "hello", "username": "Alice"}   first message after connecting
    chat     {"type": "chat", "text": "hi"}
    typing   {"type": "typing", "is_typing": true}
    exit     {"type": "exit"}

server -> client
    welcome  {"type": "welcome", "chat_id": "Client-3", "text": "...", "timestamp": "..."}
    history  {"type": "history", "messages": [<chat message>, ...]}
    chat     {"type": "chat", "sender": "Client-3", "username": "Alice",
              "text": "hi", "timestamp": "..."}
    join     {"type": "join", "chat_id": "Client-3", "username": "Alice",
              "text": "...", "timestamp": "..."}
    leave    same fields as join
    typing   {"type": "typing", "chat_id": "Client-3", "username": "Alice", "is_typing": true}
    error    {"type": "error", "text": "...", "timestamp": "..."}
    shutdown {"type": "shutdown", "text": "...", "timestamp": "..."}

Timestamps are created ONLY by the server, in ISO 8601 format
(e.g. "2026-11-26T14:03:07"), so every client sees the same time for the same
message. Clients show them as [HH:MM:SS].
"""
import json
import socket
from datetime import datetime

from common import config

# The name shown for messages typed at the server console.
SERVER_NAME = "Server"


# ---------------------------------------------------------------------------
# Encoding / decoding
# ---------------------------------------------------------------------------

def encode(message):
    """Turn a message dict into bytes ready for sock.sendall(): JSON + newline."""
    return (json.dumps(message) + "\n").encode(config.ENCODING)


def decode(line):
    """
    Turn one received line (bytes, without its newline) into a message dict.

    errors="replace" means invalid UTF-8 bytes become the "?" replacement
    character instead of raising UnicodeDecodeError and crashing the thread.

    If the line is not a JSON object (for example someone connected with a
    plain telnet/netcat client and typed raw text), we treat the text as an
    ordinary chat message. That keeps the server usable from any TCP tool.
    """
    text = line.decode(config.ENCODING, errors="replace").rstrip("\r")
    try:
        message = json.loads(text)
    except json.JSONDecodeError:
        message = None
    if not isinstance(message, dict):
        message = {"type": "chat", "text": text}
    return message


def split_lines(buffer):
    """
    Pull every complete message out of a receive buffer.

    buffer: all bytes received so far that have not been processed yet.
    Returns (messages, remainder):
        messages  - list of decoded message dicts, in the order received
        remainder - bytes after the last newline (an incomplete message, or b"")

    Example: b'{"a":1}\\n{"b":2}\\n{"c"'  ->  ([{"a":1}, {"b":2}], b'{"c"')
    """
    *complete_lines, remainder = buffer.split(b"\n")
    messages = [decode(line) for line in complete_lines if line.strip()]
    return messages, remainder


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

def now_timestamp():
    """Current local time in ISO 8601 format, e.g. '2026-11-26T14:03:07'. Server side only."""
    return datetime.now().isoformat(timespec="seconds")


def format_time(timestamp):
    """Turn an ISO 8601 timestamp into 'HH:MM:SS' for display."""
    try:
        return datetime.fromisoformat(timestamp).strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return "--:--:--"


# ---------------------------------------------------------------------------
# Display helpers (used by the CLI client, the GUI client and the server console)
# ---------------------------------------------------------------------------

def sender_label(message):
    """Who sent a chat message, e.g. 'Alice (Client-3)' or 'Server'."""
    sender = message.get("sender", "?")
    if sender == SERVER_NAME:
        return SERVER_NAME
    username = message.get("username") or sender
    if username == sender:          # client never picked a name: just show the chat ID
        return sender
    return f"{username} ({sender})"


def format_message(message):
    """
    Turn a message dict into one line of text for display.

    Returns None for messages that should not be printed (e.g. typing updates).
    """
    kind = message.get("type")
    time = f"[{format_time(message.get('timestamp'))}]"
    text = message.get("text", "")

    if kind == "chat":
        return f"{time} {sender_label(message)}: {text}"
    if kind in ("welcome", "join", "leave", "shutdown", "system"):
        return f"{time} *** {text}"
    if kind == "error":
        return f"{time} [!] {text}"
    if kind == "history":
        items = message.get("messages", [])
        if not items:
            return None
        lines = [f"--- Last {len(items)} message(s) before you joined ---"]
        lines += [format_message(item) for item in items]
        lines.append("--- End of chat history ---")
        return "\n".join(line for line in lines if line)
    return None     # "typing" and unknown types are not printed


# ---------------------------------------------------------------------------
# Connecting (used by both clients)
# ---------------------------------------------------------------------------

def connect_to_server(host, port):
    """
    Open a TCP connection to the chat server.

    Returns the connected socket. On failure raises ConnectionError with a
    friendly sentence (no traceback) that the CLI or GUI can show to the user.
    """
    try:
        sock = socket.create_connection((host, port), timeout=config.CONNECT_TIMEOUT)
    except ConnectionRefusedError:
        raise ConnectionError(
            f"Could not connect to {host}:{port} - the connection was refused.\n"
            f"Is the chat server running on port {port}?"
        ) from None
    except socket.timeout:
        raise ConnectionError(f"Timed out after {config.CONNECT_TIMEOUT:.0f}s trying to reach {host}:{port}.") from None
    except OSError as error:
        raise ConnectionError(f"Could not connect to {host}:{port}: {error.strerror or error}") from None

    # create_connection() set a timeout for the connect step only. Switch back
    # to normal blocking mode so recv() waits as long as needed for messages.
    sock.settimeout(None)
    return sock


def close_socket(sock):
    """
    Shut down and close a socket, ignoring errors if it is already closed.

    shutdown(SHUT_RDWR) is what reliably wakes up ANOTHER thread that is
    blocked in recv() on this socket (its recv() returns b"" or raises).
    close() alone does not guarantee that on every operating system.
    """
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass        # already disconnected
    try:
        sock.close()
    except OSError:
        pass
