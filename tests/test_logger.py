"""Tests for the chat log in storage/logger.py."""
import json
import threading

from storage.logger import ChatLogger


def chat(text):
    return {"type": "chat", "sender": "Client-1", "username": "A", "text": text, "timestamp": "2026-11-26T10:00:00"}


def test_log_writes_json_lines(tmp_path):
    path = tmp_path / "logs" / "chat.jsonl"
    log = ChatLogger(path, history_size=5)
    log.log(chat("hello"))
    log.log({"type": "join", "text": "A joined"})
    log.close()
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [line["type"] for line in lines] == ["chat", "join"]


def test_recent_keeps_only_last_chats(tmp_path):
    log = ChatLogger(tmp_path / "chat.jsonl", history_size=3)
    for i in range(5):
        log.log(chat(str(i)))
    log.log({"type": "leave", "text": "not history"})
    assert [m["text"] for m in log.recent_messages()] == ["2", "3", "4"]
    log.close()


def test_history_survives_restart(tmp_path):
    path = tmp_path / "chat.jsonl"
    first = ChatLogger(path, history_size=10)
    first.log(chat("before restart"))
    first.close()
    with open(path, "a", encoding="utf-8") as f:
        f.write("this line is damaged\n")       # a corrupt line must be skipped, not crash
    second = ChatLogger(path, history_size=10)
    assert [m["text"] for m in second.recent_messages()] == ["before restart"]
    second.close()


def test_close_twice_and_log_after_close(tmp_path):
    log = ChatLogger(tmp_path / "chat.jsonl", history_size=3)
    log.close()
    log.close()
    log.log(chat("ignored"))        # must not raise


def test_concurrent_logging_keeps_lines_whole(tmp_path):
    path = tmp_path / "chat.jsonl"
    log = ChatLogger(path, history_size=10)
    threads = [threading.Thread(target=lambda n=n: [log.log(chat(f"{n}-{i}")) for i in range(50)]) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    log.close()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 400
    assert all(json.loads(line)["type"] == "chat" for line in lines)
