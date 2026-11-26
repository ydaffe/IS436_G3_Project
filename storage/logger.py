"""
Chat logging (server side only).

Every chat message, join, leave and server start/stop event is appended to
logs/chat_log.jsonl - one JSON object per line, the same format used on the
wire - so the file is both human-readable and easy to load back.

The last HISTORY_SIZE chat messages are also kept in memory (a deque) so a
newly joined client can be sent recent history without re-reading the file.
On start-up the deque is filled from the existing file, so history survives
a server restart.

Thread safety
-------------
Client-handler threads, the console thread and the main thread may all log
at the same moment. If two threads wrote to the file at once, their lines
could be mixed together. So EVERY access to the file and the deque happens
while holding self._lock - only one thread at a time can be inside.
"""
import json
import threading
from collections import deque


class ChatLogger:
    def __init__(self, path, history_size):
        self._lock = threading.Lock()
        self._path = path
        # deque(maxlen=N) automatically drops the oldest item when full.
        self._recent = deque(maxlen=history_size)

        path.parent.mkdir(parents=True, exist_ok=True)    # create logs/ if needed
        self._load_recent()
        # "a" = append mode: new lines go at the end, earlier sessions are kept.
        self._file = open(path, "a", encoding="utf-8")

    def _load_recent(self):
        """Fill the history deque with the last chat messages already in the file."""
        if not self._path.exists():
            return
        with open(self._path, encoding="utf-8", errors="replace") as old_log:
            for line in old_log:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue            # skip a damaged line instead of crashing
                if isinstance(entry, dict) and entry.get("type") == "chat":
                    self._recent.append(entry)

    def log(self, message):
        """Append one event (a message dict) to the log file."""
        with self._lock:
            if self._file is None:      # logger already closed during shutdown
                return
            # ensure_ascii=False keeps emoji/accents readable in the file.
            self._file.write(json.dumps(message, ensure_ascii=False) + "\n")
            self._file.flush()          # write to disk now, so nothing is lost if the server crashes
            if message.get("type") == "chat":
                self._recent.append(message)

    def recent_messages(self):
        """A copy of the most recent chat messages (oldest first)."""
        with self._lock:
            return list(self._recent)

    def close(self):
        """Flush and close the file. Safe to call more than once."""
        with self._lock:
            if self._file is not None:
                self._file.flush()
                self._file.close()
                self._file = None
