-- IS436 Group 3 - Chat application schema (from G3 ERD)
-- SQLite dialect

CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    username      VARCHAR(50)  NOT NULL UNIQUE,  -- AK
    display_name  VARCHAR(100) NOT NULL,
    status        VARCHAR(20)  NOT NULL DEFAULT 'offline',
    created_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- USERS creates CHAT_ROOMS
CREATE TABLE IF NOT EXISTS chat_rooms (
    room_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    room_name   VARCHAR(100) NOT NULL,
    created_by  INTEGER      NOT NULL REFERENCES users(user_id),
    created_at  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- USERS joins / CHAT_ROOMS contains ROOM_MEMBERS
CREATE TABLE IF NOT EXISTS room_members (
    membership_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id        INTEGER     NOT NULL REFERENCES chat_rooms(room_id),
    user_id        INTEGER     NOT NULL REFERENCES users(user_id),
    joined_at      TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    role           VARCHAR(20) NOT NULL DEFAULT 'member'
);

-- CHAT_ROOMS stores / USERS sends MESSAGES
CREATE TABLE IF NOT EXISTS messages (
    message_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id       INTEGER   NOT NULL REFERENCES chat_rooms(room_id),
    sender_id     INTEGER   NOT NULL REFERENCES users(user_id),
    message_text  TEXT      NOT NULL,
    sent_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- USERS opens CONNECTION_SESSIONS
CREATE TABLE IF NOT EXISTS connection_sessions (
    session_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER   NOT NULL REFERENCES users(user_id),
    client_address   VARCHAR(255),
    connected_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    disconnected_at  TIMESTAMP
);
