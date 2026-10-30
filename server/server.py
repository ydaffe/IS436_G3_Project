"""Chat server: accepts TCP clients and broadcasts messages to everyone in the room.

Run:  python server/server.py [host] [port]
"""
import socket
import sys
import threading
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from db import database  # noqa: E402

HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 5050
DEFAULT_ROOM = "general"
ENCODING = "utf-8"

clients = {}  # socket -> username
clients_lock = threading.Lock()
db_lock = threading.Lock()
conn = None


def broadcast(message, sender_sock=None):
    data = (message + "\n").encode(ENCODING)
    with clients_lock:
        for sock in list(clients):
            if sock is sender_sock:
                continue
            try:
                sock.sendall(data)
            except OSError:
                clients.pop(sock, None)


def handle_client(sock, addr):
    reader = sock.makefile("r", encoding=ENCODING)
    session_id = user_id = None
    username = None
    try:
        # First line from the client is its username
        username = reader.readline().strip()
        if not username:
            return

        with db_lock:
            user_id = database.get_or_create_user(conn, username)
            room_id = database.get_or_create_room(conn, DEFAULT_ROOM, user_id)
            database.join_room(conn, room_id, user_id)
            database.set_user_status(conn, user_id, "online")
            session_id = database.open_session(conn, user_id, f"{addr[0]}:{addr[1]}")

        with clients_lock:
            clients[sock] = username
        print(f"[+] {username} connected from {addr}")
        broadcast(f"* {username} joined #{DEFAULT_ROOM}")

        for line in reader:
            text = line.strip()
            if not text:
                continue
            if text == "/quit":
                break
            # TODO: commands such as /join <room>, /rooms, /users
            with db_lock:
                database.save_message(conn, room_id, user_id, text)
            broadcast(f"[{username}] {text}", sender_sock=sock)
    except (ConnectionResetError, OSError):
        pass
    finally:
        with clients_lock:
            clients.pop(sock, None)
        if session_id:
            with db_lock:
                database.close_session(conn, session_id)
                database.set_user_status(conn, user_id, "offline")
        if username:
            print(f"[-] {username} disconnected")
            broadcast(f"* {username} left")
        sock.close()


def main():
    global conn
    database.init_db()
    conn = database.get_connection()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen()
    print(f"Chat server listening on {HOST}:{PORT}")

    try:
        while True:
            sock, addr = server.accept()
            threading.Thread(target=handle_client, args=(sock, addr), daemon=True).start()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.close()


if __name__ == "__main__":
    main()
