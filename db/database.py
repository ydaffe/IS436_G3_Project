"""SQLite helpers for the chat app. Tables mirror the G3 ERD (see schema.sql)."""
import sqlite3
from pathlib import Path

DB_DIR = Path(__file__).parent
DB_PATH = DB_DIR / "chat.db"
SCHEMA_PATH = DB_DIR / "schema.sql"


def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_connection() as conn:
        conn.executescript(SCHEMA_PATH.read_text())


# --- USERS ---------------------------------------------------------------

def get_or_create_user(conn, username):
    row = conn.execute("SELECT user_id FROM users WHERE username = ?", (username,)).fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        "INSERT INTO users (username, display_name) VALUES (?, ?)", (username, username)
    )
    conn.commit()
    return cur.lastrowid


def set_user_status(conn, user_id, status):
    conn.execute("UPDATE users SET status = ? WHERE user_id = ?", (status, user_id))
    conn.commit()


# --- CHAT_ROOMS / ROOM_MEMBERS ------------------------------------------

def get_or_create_room(conn, room_name, created_by):
    row = conn.execute("SELECT room_id FROM chat_rooms WHERE room_name = ?", (room_name,)).fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        "INSERT INTO chat_rooms (room_name, created_by) VALUES (?, ?)", (room_name, created_by)
    )
    conn.commit()
    return cur.lastrowid


def join_room(conn, room_id, user_id, role="member"):
    exists = conn.execute(
        "SELECT 1 FROM room_members WHERE room_id = ? AND user_id = ?", (room_id, user_id)
    ).fetchone()
    if exists:
        return
    conn.execute(
        "INSERT INTO room_members (room_id, user_id, role) VALUES (?, ?, ?)", (room_id, user_id, role)
    )
    conn.commit()


# --- MESSAGES -------------------------------------------------------------

def save_message(conn, room_id, sender_id, text):
    conn.execute(
        "INSERT INTO messages (room_id, sender_id, message_text) VALUES (?, ?, ?)",
        (room_id, sender_id, text),
    )
    conn.commit()


# --- CONNECTION_SESSIONS --------------------------------------------------

def open_session(conn, user_id, client_address):
    cur = conn.execute(
        "INSERT INTO connection_sessions (user_id, client_address) VALUES (?, ?)",
        (user_id, client_address),
    )
    conn.commit()
    return cur.lastrowid


def close_session(conn, session_id):
    conn.execute(
        "UPDATE connection_sessions SET disconnected_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (session_id,),
    )
    conn.commit()
