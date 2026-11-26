# IS436_G3_Project — Multi-client Chat Application

IS436 Group 3. A TCP chat server and two clients (command line and Tkinter GUI), written in Python using **only the standard library** (`socket`, `threading`, `json`, `queue`, `tkinter`, `sqlite3`).

## Requirements

- Python 3.10 or newer (tested with 3.12 on Windows 11)
- No packages to install. Tkinter ships with the normal python.org installer.

On Windows, use `py` if `python` isn't recognized (for example `py server.py 5050`).

## How to run

Open one terminal for the server and one for each client. Run every command from the project folder.

**1. Start the server** (the port must be a whole number from 1025 to 65535):

```
python server.py 5050
```

To let clients on other computers connect, run `python server.py 5050 --host 0.0.0.0` and give the clients the server's IP address.

**2. Start one or more clients:**

```
python client.py 5050                  # command-line client (asks for a username)
python client.py 5050 --name Alice     # skip the username prompt
python client_gui.py 5050              # GUI client (a dialog asks for a username)
python client.py 5050 --host 192.168.1.20   # connect to a server on another machine
```

**3. Chat.** Anything typed in a client goes to everyone. Anything typed at the server console goes to everyone as `Server`.

**4. Leave / stop:**

| Who | How |
|---|---|
| CLI client | type `exit` (or press Ctrl+C) |
| GUI client | type `exit`, click **Leave**, or close the window |
| Server | type `/quit` or `shutdown` at the server console, or press Ctrl+C |

Server console commands: `/users` (who's connected), `/help`, `/quit`, `shutdown`.

## Core requirements

| Requirement | Where |
|---|---|
| Server takes the port as an argument and checks it is an integer from 1025 to 65535 | `server.py` `main()`, `common/config.py` `parse_port()` |
| Server accepts connections and sends a welcome message | `server.py` `accept_loop()`, `send_welcome()` |
| Clients and the server console chat with each other | `server.py` `handle_client()`, `console_loop()` |
| Client takes the port as an argument, connects, and shows how to exit (`exit`) | `client.py` `main()` |
| Both sides shut down gracefully | `server.py` `shutdown_server()`, `client.py` `main()` (`finally`) |
| Clear comments, especially threads, locks, buffering and shutdown | every file |

## Bonus features implemented

1. **Multiple clients.** Each client gets its own handler thread, and messages are broadcast to everyone.
2. **Chat IDs.** Each connection gets a unique ID (`Client-1`, `Client-2`, …), which appears in every message.
3. **Usernames.** The client sends a name when it connects, and messages show as `Alice (Client-3)`. Names are saved in the `USERS` table: `username` holds the lower-case unique key and `display_name` holds the name as typed.
4. **Timestamps.** The server stamps every message in ISO 8601. Clients display the time as `[HH:MM:SS]`.
5. **GUI.** `client_gui.py` is a Tkinter client. The CLI client is still there as a fallback.
6. **Chat logging.** The server appends every chat, join, leave and start/stop event to `logs/chat_log.jsonl`.
7. **Chat history on join.** A new client receives the last 10 chat messages from the log, and history survives a server restart.
8. **Typing indicator.** The GUI shows "Alice (Client-3) is typing…". It clears 2 seconds after the last keystroke, or when the user sends the message or leaves.
9. **Message limits.** Blank messages and messages over 500 characters are refused, and the server sends a friendly error to the sender only. The GUI shows a live `n/500` counter.
10. **Database (from our ERD).** `db/chat.db` (SQLite) stores users, the `general` room, room members, every message, and each connection session with its connect and disconnect times.

Limits such as the port range, maximum message length and history size are set in `common/config.py`.

## Project structure

```
server.py            Server entry point: accept loop, client handler threads, console thread, shutdown
client.py            Command-line client (main thread = input, daemon thread = receiver)
client_gui.py        Tkinter client (receiver thread -> queue.Queue -> GUI polls every 100 ms)
common/config.py     Shared settings (host, buffer size, exit keyword, limits) + port validation
common/protocol.py   Newline-delimited JSON protocol: encode/decode, buffering, timestamps, display
storage/logger.py    Thread-safe chat log file + in-memory recent history
db/schema.sql        Tables from the G3 ERD
db/database.py       SQLite helper functions used by the server
docs/ERD.pdf         Entity-relationship diagram
docs/TEST_PLAN.md    Step-by-step manual test cases
```

## How it works

### Threads

| Program | Thread | Waits on |
|---|---|---|
| Server | main thread: the accept loop | `accept()`, with a 1-second timeout so it can check for shutdown |
| Server | one handler thread per client (daemon) | `recv()` from that client |
| Server | console thread (daemon) | `input()` from the operator |
| CLI client | main thread | `input()` |
| CLI client | receiver thread (daemon) | `recv()` |
| GUI client | main thread: the Tk mainloop | GUI events, plus a queue check every 100 ms |
| GUI client | receiver thread (daemon) | `recv()`. This thread never touches widgets. |

### Shared state on the server

| What | Protected by |
|---|---|
| `clients` dict and the `next_id` counter | `clients_lock` |
| Each client socket | its own `send_lock`, so two broadcasts never interleave bytes |
| The database | `db_lock` |
| The log file | a lock inside `ChatLogger` |

`shutdown_event` tells every loop to stop. `broadcast()` copies the client list while holding the lock, releases the lock, and then sends to each client with `sendall()`.

### Protocol

Every message is one JSON object followed by `\n`. `recv()` data is added to a buffer, and only complete lines are processed, because TCP is a stream: one `recv()` can return half a message or several messages. The full list of message types is documented at the top of `common/protocol.py`.

### Graceful shutdown

1. The server sets `shutdown_event`.
2. It broadcasts "server is shutting down" to all clients.
3. It closes every client socket and then the listening socket.
4. It waits for the handler threads to finish.
5. It flushes and closes the log, and marks open database sessions as disconnected.
6. It exits with code 0 and no traceback.

## Testing

See [docs/TEST_PLAN.md](docs/TEST_PLAN.md).

## AI assistance disclosure

Parts of this project's code and documentation were written with help from an AI assistant (Claude, by Anthropic). Following the course policy, the related chat logs are included as supplementary material, and every group member should be able to explain the code.
