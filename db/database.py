"""
SQLite helpers for the chat server. The tables mirror the G3 ERD (see schema.sql):

    USERS               one row per username (username = AK, display_name, status)
    CHAT_ROOMS          everyone currently chats in the "general" room
    ROOM_MEMBERS        which users have joined which room
    MESSAGES            every chat message (room_id, sender_id, message_text, sent_at)
    CONNECTION_SESSIONS one row per connection (client_address, connected_at, disconnected_at)

Thread safety: the server shares ONE connection between all its threads, so
every call into this module must be made while holding the server's db_lock
(see db_run() in server.py). check_same_thread=False tells sqlite3 that we
are taking care of that ourselves.

Timestamps are passed in by the server (ISO 8601, local time) so the database
uses exactly the same times that the clients see.
"""
import sqlite3
from datetime import datetime
from pathlib import Path

DB_DIR = Path(__file__).parent
DB_PATH = DB_DIR / "chat.db"
SCHEMA_PATH = DB_DIR / "schema.sql"


def _now():
    return datetime.now().isoformat(timespec="seconds")


def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create the tables if they do not exist yet."""
    with get_connection() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


# --- USERS ---------------------------------------------------------------

def get_or_create_user(conn, username, display_name, created_at=None):
    """
    Return the user_id for a username, creating the user if needed.

    username is the unique login name (stored lower-case so "Alice" and
    "alice" are the same user); display_name is the name as the user typed it.
    """
    row = conn.execute("SELECT user_id FROM users WHERE username = ?", (username,)).fetchone()
    if row:
        conn.execute("UPDATE users SET display_name = ? WHERE user_id = ?", (display_name, row[0]))
        conn.commit()
        return row[0]
    cur = conn.execute(
        "INSERT INTO users (username, display_name, created_at) VALUES (?, ?, ?)",
        (username, display_name, created_at or _now()),
    )
    conn.commit()
    return cur.lastrowid


def set_user_status(conn, user_id, status):
    conn.execute("UPDATE users SET status = ? WHERE user_id = ?", (status, user_id))
    conn.commit()


def set_all_offline(conn):
    """Used at server shutdown: nobody is online any more."""
    conn.execute("UPDATE users SET status = 'offline'")
    conn.commit()


# --- CHAT_ROOMS / ROOM_MEMBERS ------------------------------------------

def get_or_create_room(conn, room_name, created_by):
    row = conn.execute("SELECT room_id FROM chat_rooms WHERE room_name = ?", (room_name,)).fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        "INSERT INTO chat_rooms (room_name, created_by, created_at) VALUES (?, ?, ?)",
        (room_name, created_by, _now()),
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
        "INSERT INTO room_members (room_id, user_id, role, joined_at) VALUES (?, ?, ?, ?)",
        (room_id, user_id, role, _now()),
    )
    conn.commit()


# --- MESSAGES -------------------------------------------------------------

def save_message(conn, room_id, sender_id, text, sent_at=None):
    conn.execute(
        "INSERT INTO messages (room_id, sender_id, message_text, sent_at) VALUES (?, ?, ?, ?)",
        (room_id, sender_id, text, sent_at or _now()),
    )
    conn.commit()


# --- CONNECTION_SESSIONS --------------------------------------------------

def open_session(conn, user_id, client_address, connected_at=None):
    cur = conn.execute(
        "INSERT INTO connection_sessions (user_id, client_address, connected_at) VALUES (?, ?, ?)",
        (user_id, client_address, connected_at or _now()),
    )
    conn.commit()
    return cur.lastrowid


def close_session(conn, session_id, disconnected_at=None):
    conn.execute(
        "UPDATE connection_sessions SET disconnected_at = ? WHERE session_id = ?",
        (disconnected_at or _now(), session_id),
    )
    conn.commit()


def close_open_sessions(conn, disconnected_at=None):
    """Used at server shutdown: mark every session that is still open as ended."""
    conn.execute(
        "UPDATE connection_sessions SET disconnected_at = ? WHERE disconnected_at IS NULL",
        (disconnected_at or _now(),),
    )
    conn.commit()
