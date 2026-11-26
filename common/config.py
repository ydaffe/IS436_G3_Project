"""
Shared settings for the server and both clients.

Anything the server and the clients must agree on (or that you may want to
tweak for a demo) lives here, so it only has to be changed in one place.
"""
from pathlib import Path

# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------
HOST = "127.0.0.1"      # default address. Run the server with --host 0.0.0.0 to accept LAN clients.
BUFFER_SIZE = 4096      # maximum number of bytes read by one recv() call
ENCODING = "utf-8"      # every message on the wire is UTF-8 text

MIN_PORT = 1025         # ports 0-1024 are reserved for system services
MAX_PORT = 65535        # highest possible TCP port number

ACCEPT_TIMEOUT = 1.0    # seconds. accept() wakes up this often so the server can notice a shutdown.
CONNECT_TIMEOUT = 5.0   # seconds a client waits for the server before giving up

# ---------------------------------------------------------------------------
# Chat rules
# ---------------------------------------------------------------------------
EXIT_KEYWORD = "exit"                       # a client types this to leave
SERVER_QUIT_COMMANDS = ("/quit", "shutdown")  # the server operator types one of these to stop the server

MAX_MESSAGE_LENGTH = 500    # characters allowed in one chat message
MAX_USERNAME_LENGTH = 20    # longer usernames are cut to this length
MAX_LINE_BYTES = 64 * 1024  # a single protocol line bigger than this is dropped (protects server memory)
HISTORY_SIZE = 10           # how many recent messages a newly joined client receives

# ---------------------------------------------------------------------------
# Files (server side only)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = PROJECT_ROOT / "logs" / "chat_log.jsonl"   # chat history, one JSON object per line


def parse_port(value):
    """
    Turn a command-line string into a valid TCP port number.

    Used by the server AND the clients so they validate ports the same way.
    Returns the port as an int, or raises ValueError with a message that can
    be shown to the user as-is.
    """
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"the port must be a whole number, but got {value!r}.") from None

    if not MIN_PORT <= port <= MAX_PORT:
        raise ValueError(f"the port must be between {MIN_PORT} and {MAX_PORT}, but got {port}.")
    return port
