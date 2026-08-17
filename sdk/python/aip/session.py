"""Action lifecycle and idempotency store (SPEC §6)."""
from typing import Optional, Tuple

RESULT_TO_STATE = {
    "accepted": "ACCEPTED",
    "running": "RUNNING",
    "ok": "SUCCESS",
    "failed": "FAILED",
    "timeout": "TIMEOUT",
    "rejected": "REJECTED",
}
TERMINAL = {"SUCCESS", "FAILED", "TIMEOUT", "REJECTED"}
TERMINAL_STATUS = ("ok", "failed", "timeout", "rejected")


class ActionStore:
    """Tracks per-action lifecycle state and idempotency outcomes (SPEC §6)."""

    def __init__(self) -> None:
        self.actions: dict = {}   # action_id -> {state, name, source}
        self.outcomes: dict = {}  # action_id -> (status, result_id) once terminal
        self.violations: list = []  # (invariant, action_id, detail)

    def register(self, action_id: str, name: str, source: str) -> dict:
        if action_id not in self.actions:
            self.actions[action_id] = {"state": "PENDING", "name": name, "source": source}
        return self.actions[action_id]

    def mark(self, action_id: str, status: str, result_id: Optional[str] = None) -> str:
        """Apply a result status to an action.

        Returns "ok" normally, or one of:
        "invalid_status", "unknown_action", "after_terminal" (I6 violation).
        """
        state = RESULT_TO_STATE.get(status)
        if state is None:
            return "invalid_status"
        action = self.actions.get(action_id)
        if action is None:
            return "unknown_action"
        if action["state"] in TERMINAL and status not in TERMINAL_STATUS:
            self.violations.append(("I6", action_id, status))
            return "after_terminal"
        if status == "accepted" and action["state"] == "PENDING":
            action["state"] = "ACCEPTED"
        elif status == "running":
            action["state"] = "RUNNING"
        else:
            action["state"] = state
        if status in TERMINAL_STATUS:
            self.outcomes[action_id] = (status, result_id)
        return "ok"

    def state(self, action_id: str) -> Optional[str]:
        action = self.actions.get(action_id)
        return action["state"] if action else None

    def outcome(self, action_id: str) -> Optional[Tuple[str, Optional[str]]]:
        return self.outcomes.get(action_id)


class Session:
    """A session is externalized state: cursors, actions, lifecycle (SPEC §7.2)."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.state = "ACTIVE"
        self.actions = ActionStore()
        self.receiver = None  # injected by the peer/gateway that owns the wire

    def cursors(self) -> dict:
        return self.receiver.cursors(self.session_id) if self.receiver else {}

    def expire(self) -> None:
        self.state = "EXPIRED"

    def is_active(self) -> bool:
        return self.state == "ACTIVE"