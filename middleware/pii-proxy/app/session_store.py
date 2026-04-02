import threading
import time
from collections import defaultdict


class SessionStore:
    def __init__(self, ttl_hours: int = 24):
        self._lock = threading.Lock()
        self._sessions: dict = {}
        self._ttl_seconds = ttl_hours * 3600

    def get_or_create_placeholder(self, session_id: str, label: str, entity_text: str) -> str:
        normalized = entity_text.lower().strip()

        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = {
                    "mappings": {},
                    "counters": defaultdict(int),
                    "last_accessed": time.time(),
                }

            session = self._sessions[session_id]
            session["last_accessed"] = time.time()

            key = (label, normalized)
            if key in session["mappings"]:
                return session["mappings"][key]

            session["counters"][label] += 1
            placeholder = f"[{label}_{session['counters'][label]}]"
            session["mappings"][key] = placeholder
            return placeholder

    def cleanup_expired(self) -> int:
        now = time.time()
        with self._lock:
            expired = [
                sid for sid, data in self._sessions.items()
                if now - data["last_accessed"] > self._ttl_seconds
            ]
            for sid in expired:
                del self._sessions[sid]
        return len(expired)

    @property
    def active_session_count(self) -> int:
        with self._lock:
            return len(self._sessions)
