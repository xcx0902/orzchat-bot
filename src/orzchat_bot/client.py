"""Async WebSocket client for OrzChat matchmaking and text messages."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import TracebackType

from websockets.asyncio.client import ClientConnection, connect as websocket_connect
from websockets.exceptions import ConnectionClosed, ConnectionClosedOK, WebSocketException
from websockets.protocol import State

from .auth import DEFAULT_AUTH_SALT, build_join_auth

DEFAULT_SERVER_URL = "wss://ws.orzchat.com:443/"
DEFAULT_ORIGIN = "https://orzchat.com"
# OrzChat rejects clients that use websockets' default user agent with
# "Unauthorized".  A normal browser user agent is accepted.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 orzchat-bot/0.1"
)
MAX_MESSAGE_CHARS = 300


class ChatState(StrEnum):
    """State of the socket and the latest matchmaking event."""

    DISCONNECTED = "disconnected"
    WAITING = "waiting"
    MATCHED = "matched"
    PARTNER_DISCONNECTED = "partner_disconnected"


class OrzChatError(Exception):
    """Base class for OrzChat client errors."""


class OrzChatConnectionError(OrzChatError):
    """The WebSocket could not be opened."""


class OrzChatProtocolError(OrzChatError):
    """The server sent a frame that does not match the protocol."""


class OrzChatStateError(OrzChatError):
    """The requested operation is not valid in the current chat state."""


class OrzChatClosed(OrzChatError):
    """The WebSocket closed.

    ``clean`` is true for a normal close (codes 1000 and 1001).  A rejected
    join usually arrives as code 4003 after an ``error`` event.
    """

    def __init__(self, code: int, reason: str, *, clean: bool) -> None:
        self.code = code
        self.reason = reason
        self.clean = clean
        detail = f"OrzChat closed the connection (code {code}"
        if reason:
            detail += f": {reason}"
        detail += ")"
        if code == 4003:
            detail += "; the join authorization was rejected."
        super().__init__(detail)


@dataclass(frozen=True, slots=True)
class ChatEvent:
    """A server event plus its complete JSON payload in ``data``."""

    type: str
    data: Mapping[str, object]

    @property
    def text(self) -> str | None:
        value = self.data.get("text")
        return value if isinstance(value, str) else None

    @property
    def message(self) -> str | None:
        value = self.data.get("message")
        return value if isinstance(value, str) else None


_EVENT_STATES = {
    "waiting": ChatState.WAITING,
    "matched": ChatState.MATCHED,
    "partner_disconnected": ChatState.PARTNER_DISCONNECTED,
}


class OrzChatClient:
    """One connection to an OrzChat room or the public queue."""

    def __init__(
        self,
        room_id: str = "",
        *,
        server_url: str = DEFAULT_SERVER_URL,
        auth_salt: str = DEFAULT_AUTH_SALT,
        origin: str = DEFAULT_ORIGIN,
        user_agent: str = DEFAULT_USER_AGENT,
        open_timeout: float = 10.0,
        proxy: str | None = None,
        max_message_chars: int = MAX_MESSAGE_CHARS,
    ) -> None:
        if not isinstance(room_id, str):
            raise TypeError("room_id must be a string.")
        if max_message_chars < 1:
            raise ValueError("max_message_chars must be positive.")
        self.room_id = room_id
        self.server_url = server_url
        self.auth_salt = auth_salt
        self.origin = origin
        self.user_agent = user_agent
        self.open_timeout = open_timeout
        self.proxy = proxy
        self.max_message_chars = max_message_chars
        self._socket: ClientConnection | None = None
        self._state = ChatState.DISCONNECTED
        self._lifecycle_lock = asyncio.Lock()

    @property
    def state(self) -> ChatState:
        """The latest matchmaking state consumed by this client."""
        if self._socket is None or self._socket.state is not State.OPEN:
            return ChatState.DISCONNECTED
        return self._state

    async def connect(self) -> None:
        """Open the WebSocket and send the room join frame."""
        async with self._lifecycle_lock:
            if self._socket is not None and self._socket.state is State.OPEN:
                return
            await self._close()
            await self._open_and_join()

    async def send_message(self, text: str) -> None:
        """Send a text message to the matched partner."""
        if not isinstance(text, str):
            raise TypeError("text must be a string.")
        if not text.strip():
            raise ValueError("Chat text must contain a non-whitespace character.")
        if len(text) > self.max_message_chars:
            raise ValueError(
                f"Chat text is {len(text)} characters; the limit is {self.max_message_chars}."
            )
        socket = self._require_socket()
        if self._state is not ChatState.MATCHED:
            raise OrzChatStateError("Wait for a matched event before sending a message.")
        try:
            await socket.send(json.dumps({"type": "message", "text": text}))
        except ConnectionClosed as exc:
            raise _closed_error(exc) from exc

    async def receive_event(self, *, timeout: float | None = None) -> ChatEvent:
        """Receive one event.  A timeout raises ``TimeoutError``."""
        socket = self._require_socket()
        async with asyncio.timeout(timeout):
            return await self._receive_event(socket)

    async def events(self) -> AsyncIterator[ChatEvent]:
        """Yield events until the connection closes normally.

        An abnormal close raises :class:`OrzChatClosed`.  Use one event
        consumer per client.
        """
        socket = self._require_socket()
        while self._socket is socket:
            try:
                event = await self._receive_event(socket)
            except OrzChatClosed as exc:
                if exc.clean:
                    return
                raise
            if self._socket is socket:
                yield event

    async def close(self) -> None:
        """Close the WebSocket, if open."""
        async with self._lifecycle_lock:
            await self._close()

    async def __aenter__(self) -> OrzChatClient:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    async def _open_and_join(self) -> None:
        """Open a socket and send the join frame while holding the lock."""
        try:
            socket = await websocket_connect(
                self.server_url,
                origin=self.origin,
                user_agent_header=self.user_agent,
                open_timeout=self.open_timeout,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                max_size=1024 * 1024,
                # ``None`` deliberately bypasses HTTP(S)_PROXY.  A dead local
                # proxy is a common cause of confusing failures.
                proxy=self.proxy,
            )
        except (OSError, TimeoutError, ValueError, WebSocketException) as exc:
            raise OrzChatConnectionError(
                f"Could not connect to {self.server_url}: {exc}"
            ) from exc

        join = {
            "type": "join",
            "room_id": self.room_id,
            # Generate the timestamp after the handshake so a slow network
            # does not age the signature.
            "auth": build_join_auth(self.room_id, salt=self.auth_salt),
        }
        try:
            await socket.send(json.dumps(join))
        except ConnectionClosed as exc:
            await socket.close()
            raise _closed_error(exc) from exc

        self._socket = socket
        self._state = ChatState.WAITING

    async def _close(self) -> None:
        socket = self._socket
        self._socket = None
        self._state = ChatState.DISCONNECTED
        if socket is not None:
            try:
                await socket.close()
            except Exception:
                # Closing is best-effort; the socket may already be gone.
                pass

    def _require_socket(self) -> ClientConnection:
        if self._socket is None:
            raise OrzChatStateError("Connect to OrzChat first.")
        return self._socket

    async def _receive_event(self, socket: ClientConnection) -> ChatEvent:
        try:
            raw = await socket.recv()
        except ConnectionClosed as exc:
            raise _closed_error(exc) from exc

        try:
            data = json.loads(raw)
        except (ValueError, RecursionError, TypeError) as exc:
            raise OrzChatProtocolError("Expected a JSON event from OrzChat.") from exc
        if not isinstance(data, dict):
            raise OrzChatProtocolError("Expected an OrzChat event object.")
        event_type = data.get("type")
        if not isinstance(event_type, str):
            raise OrzChatProtocolError("Expected an OrzChat event with a string type.")
        if event_type == "message" and not isinstance(data.get("text"), str):
            raise OrzChatProtocolError("Expected a message event with a string text field.")

        if self._socket is socket:
            self._state = _EVENT_STATES.get(event_type, self._state)
        return ChatEvent(event_type, data)


def _closed_error(exc: ConnectionClosed) -> OrzChatClosed:
    code = exc.rcvd.code if exc.rcvd is not None else 1006
    reason = exc.rcvd.reason if exc.rcvd is not None else ""
    return OrzChatClosed(code, reason, clean=isinstance(exc, ConnectionClosedOK))
