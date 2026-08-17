"""Per-stream sequence tracking (SPEC §5.4)."""


class Sequencer:
    """Assigns monotonically increasing seq per (session, source)."""

    def __init__(self) -> None:
        self._last: dict = {}

    def next(self, session: str, source: str) -> int:
        key = (session, source)
        self._last[key] = self._last.get(key, 0) + 1
        return self._last[key]

    def last(self, session: str, source: str) -> int:
        return self._last.get((session, source), 0)


class Receiver:
    """Classifies incoming messages against per-stream cursors (SPEC §5.4).

    Returns one of: "accept", "duplicate", "stale", "gap".
    """

    def __init__(self) -> None:
        self._applied_seq: dict = {}   # (session, source) -> last applied seq
        self._applied_count: dict = {}  # (session, source) -> messages applied
        self._ids: dict = {}            # (session, source) -> set of applied ids
        self.history: list = []         # applied (session, source, seq), in order

    def _key(self, msg) -> tuple:
        return (msg.session, msg.source)

    def classify(self, msg) -> str:
        key = self._key(msg)
        last = self._applied_seq.get(key, 0)
        if msg.seq == last + 1:
            return "accept"
        if msg.seq <= last:
            return "duplicate" if msg.id in self._ids.get(key, ()) else "stale"
        return "gap"

    def apply(self, msg) -> None:
        key = self._key(msg)
        self._applied_seq[key] = msg.seq
        self._applied_count[key] = self._applied_count.get(key, 0) + 1
        self._ids.setdefault(key, set()).add(msg.id)
        self.history.append((msg.session, msg.source, msg.seq))

    def cursor(self, session: str, source: str) -> int:
        return self._applied_seq.get((session, source), 0)

    def cursors(self, session: str) -> dict:
        return {s: seq for (sess, s), seq in self._applied_seq.items() if sess == session}

    def applied_count(self, session: str, source: str) -> int:
        return self._applied_count.get((session, source), 0)