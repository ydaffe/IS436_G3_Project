"""
End-to-end tests: start the real server.py in a subprocess and talk to it over TCP.

Each test gets its own server on a free port, with the chat log and database
redirected to a temporary folder (CHAT_LOG_FILE / CHAT_DB_FILE).
"""
import json
import os
import socket
import sqlite3
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_script(*args, env=None):
    return subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True,
                          timeout=20, env=env, encoding="utf-8")


class TestClient:
    """A minimal protocol client used to drive the server."""
    __test__ = False        # not a pytest test class

    def __init__(self, port, name=None, hello=True):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.sock.settimeout(0.2)
        self.buffer = b""
        self.pending = []
        if hello:
            self.send({"type": "hello", "username": name})

    def send(self, message):
        self.sock.sendall((json.dumps(message) + "\n").encode())

    def wait_for(self, predicate, timeout=5.0):
        """Return the first received message matching predicate, or None (also None on disconnect)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            for message in self.pending:
                if predicate(message):
                    self.pending.remove(message)
                    return message
            try:
                data = self.sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                return None
            if not data:
                return None
            self.buffer += data
            *lines, self.buffer = self.buffer.split(b"\n")
            self.pending += [json.loads(line) for line in lines if line.strip()]
        return None

    def welcome(self):
        return self.wait_for(lambda m: m["type"] == "welcome")

    def close(self):
        self.sock.close()


@pytest.fixture
def server(tmp_path):
    """Start server.py on a free port; yields (process, port, env, tmp_path) and stops it afterwards."""
    port = free_port()
    env = dict(os.environ, PYTHONIOENCODING="utf-8",
               CHAT_LOG_FILE=str(tmp_path / "chat_log.jsonl"), CHAT_DB_FILE=str(tmp_path / "chat.db"))
    proc = subprocess.Popen([sys.executable, "server.py", str(port)], cwd=ROOT, env=env, text=True,
                            encoding="utf-8", stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    # Wait until the server accepts connections.
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("server did not start:\n" + proc.stdout.read())
    yield proc, port, env, tmp_path
    if proc.poll() is None:
        proc.kill()
        proc.wait()


def console(proc, line):
    proc.stdin.write(line + "\n")
    proc.stdin.flush()


# ---------------------------------------------------------------------------
# Command-line argument checks (no server needed)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("port", ["abc", "80", "1024", "65536", "50.5"])
def test_server_rejects_invalid_port(port):
    result = run_script("server.py", port)
    assert result.returncode == 1
    assert "Error:" in result.stderr and "Traceback" not in result.stderr


def test_client_rejects_invalid_port():
    result = run_script("client.py", "99999", "--name", "x")
    assert result.returncode == 1 and "Traceback" not in result.stderr


def test_client_connection_refused_is_friendly():
    result = run_script("client.py", str(free_port()), "--name", "x")
    assert result.returncode == 1
    assert "refused" in result.stderr and "Traceback" not in result.stderr


def test_second_server_on_same_port_fails(server):
    _, port, env, _ = server
    result = run_script("server.py", str(port), env=env)
    assert result.returncode == 1 and "cannot listen" in result.stderr


# ---------------------------------------------------------------------------
# Chat behaviour
# ---------------------------------------------------------------------------

def test_welcome_ids_and_broadcast(server):
    _, port, _, _ = server
    alice = TestClient(port, "Alice")
    welcome = alice.welcome()
    assert welcome["chat_id"].startswith("Client-") and "'exit'" in welcome["text"]
    bob = TestClient(port, "Bob")
    bob_id = bob.welcome()["chat_id"]
    assert bob_id != welcome["chat_id"]
    assert alice.wait_for(lambda m: m["type"] == "join" and m["text"].startswith(f"Bob ({bob_id})"))

    alice.send({"type": "chat", "text": "hello everyone"})
    received = bob.wait_for(lambda m: m["type"] == "chat")
    assert received["sender"] == welcome["chat_id"]
    assert received["username"] == "Alice"
    assert received["text"] == "hello everyone"
    assert "T" in received["timestamp"]           # ISO 8601 timestamp from the server
    assert alice.wait_for(lambda m: m["type"] == "chat" and m["text"] == "hello everyone")


def test_message_limits_error_only_to_sender(server):
    _, port, _, _ = server
    alice, bob = TestClient(port, "Alice"), TestClient(port, "Bob")
    alice.welcome(), bob.welcome()
    alice.send({"type": "chat", "text": "   "})
    assert "Empty" in alice.wait_for(lambda m: m["type"] == "error")["text"]
    alice.send({"type": "chat", "text": "x" * 501})
    assert "501" in alice.wait_for(lambda m: m["type"] == "error")["text"]
    alice.send({"type": "chat", "text": "y" * 500})
    assert bob.wait_for(lambda m: m["type"] == "chat")["text"] == "y" * 500   # first chat Bob sees
    assert bob.wait_for(lambda m: m["type"] == "error", timeout=0.5) is None


def test_typing_goes_to_others_only(server):
    _, port, _, _ = server
    alice, bob = TestClient(port, "Alice"), TestClient(port, "Bob")
    alice.welcome(), bob.welcome()
    alice.send({"type": "typing", "is_typing": True})
    typing = bob.wait_for(lambda m: m["type"] == "typing")
    assert typing["is_typing"] is True and typing["username"] == "Alice"
    assert alice.wait_for(lambda m: m["type"] == "typing", timeout=0.5) is None


def test_console_message_is_broadcast_as_server(server):
    proc, port, _, _ = server
    alice = TestClient(port, "Alice")
    alice.welcome()
    alice.wait_for(lambda m: m["type"] == "join")
    console(proc, "hello from the console")
    message = alice.wait_for(lambda m: m["type"] == "chat")
    assert message["sender"] == "Server" and message["text"] == "hello from the console"


def test_exit_and_abrupt_disconnect_are_announced(server):
    _, port, _, _ = server
    watcher = TestClient(port, "Watcher")
    watcher.welcome()
    leaver = TestClient(port, "Leaver")
    leaver.welcome()
    leaver.send({"type": "exit"})
    assert "left the chat" in watcher.wait_for(lambda m: m["type"] == "leave")["text"]

    crasher = TestClient(port, "Crasher")
    crasher.welcome()
    watcher.wait_for(lambda m: m["type"] == "join" and "Crasher" in m["text"])
    # SO_LINGER 0 makes close() send a TCP reset, like a killed process.
    crasher.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    crasher.close()
    leave = watcher.wait_for(lambda m: m["type"] == "leave" and "Crasher" in m["text"])
    assert leave is not None


def test_raw_text_client(server):
    _, port, _, _ = server
    watcher = TestClient(port, "Watcher")
    watcher.welcome()
    raw = TestClient(port, hello=False)
    raw.welcome()
    raw.sock.sendall(b"plain text hi\r\n")
    message = watcher.wait_for(lambda m: m["type"] == "chat")
    assert message["text"] == "plain text hi" and message["username"] == message["sender"]


def test_history_sent_on_join(server):
    _, port, _, _ = server
    alice = TestClient(port, "Alice")
    alice.welcome()
    for i in range(12):
        alice.send({"type": "chat", "text": f"msg {i}"})
    assert alice.wait_for(lambda m: m.get("text") == "msg 11")
    late = TestClient(port, "Late")
    late.welcome()
    history = late.wait_for(lambda m: m["type"] == "history")
    assert [m["text"] for m in history["messages"]] == [f"msg {i}" for i in range(2, 12)]


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------

def test_graceful_shutdown_with_clients_connected(server):
    proc, port, _, tmp_path = server
    alice = TestClient(port, "Alice")
    alice.welcome()
    alice.send({"type": "chat", "text": "logged message"})
    alice.wait_for(lambda m: m["type"] == "chat")

    console(proc, "/quit")
    assert alice.wait_for(lambda m: m["type"] == "shutdown")
    assert alice.wait_for(lambda m: False, timeout=2) is None      # connection closed by server
    output, _ = proc.communicate(timeout=10)
    assert proc.returncode == 0
    assert "Server stopped" in output and "Traceback" not in output

    log = (tmp_path / "chat_log.jsonl").read_text(encoding="utf-8")
    assert "logged message" in log and "Server stopped." in log
    db = sqlite3.connect(tmp_path / "chat.db")
    try:
        assert db.execute("SELECT COUNT(*) FROM connection_sessions WHERE disconnected_at IS NULL").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM users WHERE status = 'online'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
    finally:
        db.close()


def test_cli_client_end_to_end(server):
    proc, port, env, _ = server
    bob = TestClient(port, "Bob")
    bob.welcome()
    cli = subprocess.Popen([sys.executable, "client.py", str(port), "--name", "Cli"], cwd=ROOT, env=env,
                           text=True, encoding="utf-8", stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
    try:
        assert bob.wait_for(lambda m: m["type"] == "join" and "Cli" in m["text"])
        cli.stdin.write("from the cli\n")
        cli.stdin.flush()
        assert bob.wait_for(lambda m: m["type"] == "chat")["text"] == "from the cli"
        bob.send({"type": "chat", "text": "reply"})
        time.sleep(0.5)
        output, _ = cli.communicate("exit\n", timeout=10)
    finally:
        if cli.poll() is None:
            cli.kill()
    assert cli.returncode == 0
    assert "Type 'exit'" in output and "Welcome to the IS436" in output
    assert "Bob (Client-" in output and "reply" in output
    assert "Traceback" not in output
