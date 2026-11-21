import asyncio
from dataclasses import replace

import pytest

from orzchat_bot.bot import AuthError, Bot, BotError
from orzchat_bot.client import ChatEvent, ChatState, OrzChatStateError
from orzchat_bot.config import Settings


def make_settings(**overrides) -> Settings:
    base = Settings(
        room_id="test-room",
        model="test-model",
        api_key="test-key",
        once=True,
        debounce_seconds=0.01,
        log_messages=False,
    )
    return replace(base, **overrides)


class FakeClient:
    def __init__(
        self,
        events: list[ChatEvent],
        *,
        message_delay: float = 0.02,
        disconnect_delay: float = 0.2,
    ) -> None:
        self._events = events
        self._message_delay = message_delay
        self._disconnect_delay = disconnect_delay
        self.sent: list[str] = []
        self.state = ChatState.DISCONNECTED
        self.closed = False

    async def connect(self) -> None:
        self.state = ChatState.WAITING

    async def close(self) -> None:
        self.state = ChatState.DISCONNECTED
        self.closed = True

    async def send_message(self, text: str) -> None:
        if self.state is not ChatState.MATCHED:
            raise OrzChatStateError("not matched")
        self.sent.append(text)

    async def events(self):
        for event in self._events:
            if event.type == "partner_disconnected":
                await asyncio.sleep(self._disconnect_delay)
                self.state = ChatState.PARTNER_DISCONNECTED
            elif event.type == "matched":
                self.state = ChatState.MATCHED
            yield event
            if event.type == "message":
                await asyncio.sleep(self._message_delay)


class FakeLLM:
    def __init__(self, reply: str = "Hi there!") -> None:
        self.reply = reply
        self.calls: list[list[dict[str, str]]] = []

    async def complete(self, messages) -> str:
        self.calls.append([dict(message) for message in messages])
        return self.reply


async def test_bot_replies_to_a_message():
    client = FakeClient(
        [
            ChatEvent("waiting", {}),
            ChatEvent("matched", {}),
            ChatEvent("message", {"text": "hello"}),
            ChatEvent("partner_disconnected", {}),
        ]
    )
    llm = FakeLLM("Hey! How are you?")
    bot = Bot(make_settings(), llm=llm, client_factory=lambda: client)  # type: ignore[arg-type]

    await bot.run()

    assert client.sent == ["Hey! How are you?"]
    assert client.closed is True
    assert llm.calls[0][0]["role"] == "system"
    assert llm.calls[0][-1] == {"role": "user", "content": "hello"}


async def test_debounce_combines_rapid_messages():
    client = FakeClient(
        [
            ChatEvent("matched", {}),
            ChatEvent("message", {"text": "one"}),
            ChatEvent("message", {"text": "two"}),
            ChatEvent("partner_disconnected", {}),
        ],
        message_delay=0.02,
        disconnect_delay=0.2,
    )
    llm = FakeLLM("combined")
    bot = Bot(
        make_settings(debounce_seconds=0.1),
        llm=llm,
        client_factory=lambda: client,  # type: ignore[arg-type]
    )

    await bot.run()

    assert client.sent == ["combined"]
    assert len(llm.calls) == 1
    assert llm.calls[0][-1] == {"role": "user", "content": "one\ntwo"}


async def test_history_is_used_on_the_next_turn():
    client = FakeClient(
        [
            ChatEvent("matched", {}),
            ChatEvent("message", {"text": "one"}),
            ChatEvent("message", {"text": "two"}),
            ChatEvent("partner_disconnected", {}),
        ],
        message_delay=0.02,
        disconnect_delay=0.3,
    )
    llm = FakeLLM("reply")
    bot = Bot(
        make_settings(debounce_seconds=0.0),
        llm=llm,
        client_factory=lambda: client,  # type: ignore[arg-type]
    )

    await bot.run()

    assert client.sent == ["reply", "reply"]
    assert len(llm.calls) == 2
    assert llm.calls[1][1:3] == [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "reply"},
    ]
    assert llm.calls[1][-1] == {"role": "user", "content": "two"}


async def test_reply_limit_stops_after_the_configured_count():
    client = FakeClient(
        [
            ChatEvent("matched", {}),
            ChatEvent("message", {"text": "one"}),
            ChatEvent("message", {"text": "two"}),
            ChatEvent("partner_disconnected", {}),
        ],
        message_delay=0.02,
        disconnect_delay=0.2,
    )
    llm = FakeLLM("reply")
    bot = Bot(
        make_settings(debounce_seconds=0.0, max_replies_per_chat=1),
        llm=llm,
        client_factory=lambda: client,  # type: ignore[arg-type]
    )

    await bot.run()

    assert client.sent == ["reply"]


async def test_dry_run_does_not_call_the_model():
    client = FakeClient(
        [
            ChatEvent("matched", {}),
            ChatEvent("message", {"text": "hello"}),
            ChatEvent("partner_disconnected", {}),
        ]
    )
    bot = Bot(
        make_settings(dry_run=True),
        llm=None,
        client_factory=lambda: client,  # type: ignore[arg-type]
    )

    await bot.run()

    assert client.sent == []


async def test_auth_error_event_stops_the_bot():
    client = FakeClient([ChatEvent("error", {"message": "Unauthorized"})])
    bot = Bot(make_settings(), llm=FakeLLM(), client_factory=lambda: client)  # type: ignore[arg-type]

    with pytest.raises(AuthError):
        await bot.run()


def test_llm_is_required_unless_dry_run():
    with pytest.raises(BotError):
        Bot(make_settings(), llm=None)
    Bot(make_settings(dry_run=True), llm=None)
