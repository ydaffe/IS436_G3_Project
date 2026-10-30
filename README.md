# IS436_G3_Project

IS436 Group 3, an online chat application built with socket programming. One server, multiple clients, with chat rooms, messages and connection sessions stored in SQLite.

## Status

Checkpoint 1: repo and project skeleton. A basic server/client works; everyone joins the `general` room.

## Structure

```
server/server.py   TCP server: one thread per client, broadcasts messages
client/client.py   Command-line client
db/schema.sql      Tables from our ERD (users, chat_rooms, room_members, messages, connection_sessions)
db/database.py     SQLite helper functions used by the server
docs/              Diagrams (ERD, DFD) and requirements
```

## Requirements

Python 3.10+. No extra packages; it only uses the standard library (`socket`, `threading`, `sqlite3`).

## Running

Start the server:

```
python server/server.py
```

In another terminal (one per user), start a client:

```
python client/client.py
```

Both take optional `host port` arguments (default `127.0.0.1 5050`). To chat across machines, run the server with `0.0.0.0` and point clients at the server's IP.

## Next steps

- Room commands: `/join <room>`, `/rooms`, `/users`
- Show message history when joining a room
- Room roles (owner/member) from `room_members.role`
