import asyncio
import json

import pytest
from websockets.asyncio.server import serve

from orzchat_bot.client import (
    ChatState,
    OrzChatClient,
    OrzChatClosed,
    OrzChatProtocolError,
    OrzChatStateError,
)


async def test_join_send_and_receive_roundtrip():
    joins: list[dict[str, object]] = []
    messages: list[dict[str, object]] = []

    async def handler(websocket):
        raw = await websocket.recv()
        joins.append(json.loads(raw))
        assert websocket.request.headers["Origin"] == "https://orzchat.com"
        assert "orzchat-bot" in websocket.request.headers["User-Agent"]

        await websocket.send(json.dumps({"type": "waiting", "message": "Waiting"}))
        await websocket.send(json.dumps({"type": "matched", "message": "Matched"}))
        async for raw in websocket:
            data = json.loads(raw)
            messages.append(data)
            await websocket.send(json.dumps({"type": "message", "text": "echo: " + data["text"]}))
            await websocket.send(
                json.dumps({"type": "partner_disconnected", "message": "Partner left"})
            )
            await websocket.close()
            return

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        url = f"ws://127.0.0.1:{port}"
        client = OrzChatClient("room-1", server_url=url, proxy=None)
        seen = []
        async with client:
            async for event in client.events():
                seen.append(event)
                if event.type == "matched":
                    assert client.state is ChatState.MATCHED
                    await client.send_message("hi")
                elif event.type == "message":
                    assert event.text == "echo: hi"
                    break

    assert [event.type for event in seen] == ["waiting", "matched", "message"]
    assert joins[0]["type"] == "join"
    assert joins[0]["room_id"] == "room-1"
    auth = joins[0]["auth"]
    assert isinstance(auth, dict)
    assert set(auth) == {"ts", "nonce", "sig"}
    assert messages == [{"type": "message", "text": "hi"}]


async def test_send_before_match_is_rejected():
    async def handler(websocket):
        await websocket.recv()
        await websocket.send(json.dumps({"type": "waiting"}))
        await asyncio.sleep(0.5)

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with OrzChatClient(
            "", server_url=f"ws://127.0.0.1:{port}", proxy=None
        ) as client:
            await client.receive_event(timeout=2)
            assert client.state is ChatState.WAITING
            with pytest.raises(OrzChatStateError):
                await client.send_message("too soon")


async def test_unauthorized_close_is_reported_with_code():
    async def handler(websocket):
        await websocket.recv()
        await websocket.send(json.dumps({"type": "error", "message": "Unauthorized"}))
        await websocket.close(code=4003, reason="Forbidden")

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        with pytest.raises(OrzChatClosed) as info:
            async with OrzChatClient(
                "", server_url=f"ws://127.0.0.1:{port}", proxy=None
            ) as client:
                async for _ in client.events():
                    pass
    assert info.value.code == 4003
    assert info.value.clean is False


async def test_malformed_event_is_a_protocol_error():
    async def handler(websocket):
        await websocket.recv()
        await websocket.send("this is not JSON")
        await asyncio.sleep(0.5)

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        with pytest.raises(OrzChatProtocolError):
            async with OrzChatClient(
                "", server_url=f"ws://127.0.0.1:{port}", proxy=None
            ) as client:
                async for _ in client.events():
                    pass
