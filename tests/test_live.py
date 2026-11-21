import asyncio
import os
import secrets

import pytest

from orzchat_bot.client import OrzChatClient, OrzChatConnectionError

pytestmark = pytest.mark.skipif(
    os.getenv("ORZCHAT_LIVE_TEST") != "1",
    reason="set ORZCHAT_LIVE_TEST=1 to use the real OrzChat service",
)


async def _roundtrip() -> None:
    room = "bot-live-" + secrets.token_hex(4)
    async with (
        OrzChatClient(room, proxy=None, open_timeout=20) as first,
        OrzChatClient(room, proxy=None, open_timeout=20) as second,
    ):
        assert (await first.receive_event(timeout=10)).type == "waiting"
        assert (await second.receive_event(timeout=10)).type == "matched"
        assert (await first.receive_event(timeout=10)).type == "matched"

        await second.send_message("live test ping")
        event = await first.receive_event(timeout=10)
        assert event.type == "message"
        assert event.text == "live test ping"

        await first.send_message("live test pong")
        event = await second.receive_event(timeout=10)
        assert event.type == "message"
        assert event.text == "live test pong"


async def test_live_two_clients_match_and_exchange_messages():
    # The public WebSocket endpoint occasionally times out during its TLS
    # handshake.  Retry once so a transient network error does not make the
    # opt-in live test look like a protocol regression.
    last_error: OrzChatConnectionError | None = None
    for attempt in range(2):
        try:
            await _roundtrip()
            return
        except OrzChatConnectionError as exc:
            last_error = exc
            if attempt == 0:
                await asyncio.sleep(1)
    assert last_error is not None
    raise last_error
