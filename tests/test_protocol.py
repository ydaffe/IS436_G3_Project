"""Tests for the newline-delimited JSON protocol in common/protocol.py."""
from common import protocol


def test_encode_is_one_json_line():
    data = protocol.encode({"type": "chat", "text": "line one\nline two"})
    # Exactly one real newline, at the end: newlines inside the text are escaped.
    assert data.endswith(b"\n")
    assert data.count(b"\n") == 1


def test_encode_decode_round_trip():
    message = {"type": "chat", "text": "café ☕ 😀"}
    assert protocol.decode(protocol.encode(message).rstrip(b"\n")) == message


def test_split_lines_keeps_partial_message():
    messages, rest = protocol.split_lines(b'{"type":"chat","text":"a"}\n{"type":"ch')
    assert messages == [{"type": "chat", "text": "a"}]
    assert rest == b'{"type":"ch'


def test_split_lines_handles_glued_messages():
    buffer = protocol.encode({"type": "chat", "text": "1"}) + protocol.encode({"type": "chat", "text": "2"})
    messages, rest = protocol.split_lines(buffer)
    assert [m["text"] for m in messages] == ["1", "2"]
    assert rest == b""


def test_split_lines_reassembles_across_reads():
    buffer = b""
    received = []
    for chunk in (b'{"type":"chat",', b'"text":"split"}', b"\n"):
        buffer += chunk
        messages, buffer = protocol.split_lines(buffer)
        received += messages
    assert received == [{"type": "chat", "text": "split"}]


def test_split_lines_skips_blank_lines():
    messages, rest = protocol.split_lines(b"\n\r\n")
    assert messages == [] and rest == b""


def test_decode_invalid_utf8_is_replaced_not_raised():
    message = protocol.decode(b'{"type":"chat","text":"bad \xff byte"}')
    assert message["type"] == "chat"
    assert "�" in message["text"]


def test_decode_plain_text_becomes_chat():
    assert protocol.decode(b"hello there\r") == {"type": "chat", "text": "hello there"}
    assert protocol.decode(b"[1, 2]") == {"type": "chat", "text": "[1, 2]"}


def test_format_time():
    assert protocol.format_time("2026-11-26T14:03:07") == "14:03:07"
    assert protocol.format_time(None) == "--:--:--"
    assert protocol.format_time("not a time") == "--:--:--"


def test_sender_label():
    assert protocol.sender_label({"sender": "Client-3", "username": "Alice"}) == "Alice (Client-3)"
    assert protocol.sender_label({"sender": "Client-3", "username": "Client-3"}) == "Client-3"
    assert protocol.sender_label({"sender": "Server", "username": "Server"}) == "Server"


def test_format_message():
    ts = "2026-11-26T14:03:07"
    chat = {"type": "chat", "sender": "Client-3", "username": "Alice", "text": "hi", "timestamp": ts}
    assert protocol.format_message(chat) == "[14:03:07] Alice (Client-3): hi"
    assert protocol.format_message({"type": "join", "text": "x joined", "timestamp": ts}) == "[14:03:07] *** x joined"
    assert protocol.format_message({"type": "error", "text": "nope", "timestamp": ts}) == "[14:03:07] [!] nope"
    assert protocol.format_message({"type": "typing", "is_typing": True}) is None


def test_format_history():
    ts = "2026-11-26T14:03:07"
    history = {"type": "history", "messages": [
        {"type": "chat", "sender": "Server", "username": "Server", "text": "hi", "timestamp": ts}]}
    text = protocol.format_message(history)
    assert "Last 1 message(s)" in text and "[14:03:07] Server: hi" in text
    assert protocol.format_message({"type": "history", "messages": []}) is None
