"""Clock abstraction. Timeouts use a monotonic-style clock, never wall-clock
timestamps from messages (SPEC §5.5, I8). FakeClock makes retry/timeout
conformance tests deterministic.
"""
import time


class Clock:
    def now_ms(self) -> int:
        return int(time.time() * 1000)


class FakeClock:
    def __init__(self, start_ms: int = 0) -> None:
        self.t = start_ms

    def now_ms(self) -> int:
        return self.t

    def advance(self, ms: int) -> None:
        self.t += ms