"""Per-partner conversation history."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class Conversation:
    """Keep a bounded number of completed user/assistant exchanges.

    The current user message is supplied to :meth:`build_messages` and is not
    stored until a reply has actually been sent, so a failed model request never
    leaves a dangling turn in the history.
    """

    system_prompt: str
    max_exchanges: int = 10
    _turns: deque[tuple[str, str]] = field(default_factory=deque, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.max_exchanges < 0:
            raise ValueError("max_exchanges must not be negative.")

    def build_messages(self, user_text: str) -> list[dict[str, str]]:
        """Build a Chat Completions ``messages`` array for the next turn."""
        messages: list[dict[str, str]] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        for previous_user, previous_assistant in self._turns:
            messages.append({"role": "user", "content": previous_user})
            messages.append({"role": "assistant", "content": previous_assistant})
        messages.append({"role": "user", "content": user_text})
        return messages

    def record_exchange(self, user_text: str, assistant_text: str) -> None:
        """Record a completed exchange and discard the oldest ones."""
        if self.max_exchanges == 0:
            return
        self._turns.append((user_text, assistant_text))
        while len(self._turns) > self.max_exchanges:
            self._turns.popleft()

    def reset(self) -> None:
        """Forget the conversation, for example when a new partner arrives."""
        self._turns.clear()

    @property
    def exchange_count(self) -> int:
        return len(self._turns)
