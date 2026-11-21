"""The OrzChat reply bot: matchmaking, conversation, and reconnects."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from .client import (
    ChatState,
    OrzChatClient,
    OrzChatClosed,
    OrzChatConnectionError,
    OrzChatError,
    OrzChatStateError,
)
from .config import Settings
from .conversation import Conversation
from .llm import ChatCompletionClient, LLMError
from .text import fit_message, preview

logger = logging.getLogger(__name__)


class BotError(RuntimeError):
    """The bot cannot start or must stop."""


class AuthError(BotError):
    """OrzChat rejected the generated join authorization."""


class SessionResult(StrEnum):
    PARTNER_LEFT = "partner_left"
    CLOSED = "closed"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class SessionOutcome:
    result: SessionResult
    matched: bool = False
    connected: bool = False


class Bot:
    """Own one OrzChat connection at a time and answer incoming messages."""

    def __init__(
        self,
        settings: Settings,
        *,
        llm: ChatCompletionClient | None = None,
        client_factory: Callable[[], OrzChatClient] | None = None,
    ) -> None:
        if llm is None and not settings.dry_run:
            raise BotError("An LLM client is required unless dry_run is enabled.")
        self._settings = settings
        self._llm = llm
        self._client_factory = client_factory or self._make_client
        self._stop = asyncio.Event()
        self._client: OrzChatClient | None = None

    async def run(self) -> None:
        """Connect, reply, and reconnect until :meth:`stop` is called."""
        delay = self._settings.reconnect_initial
        while not self._stop.is_set():
            try:
                outcome = await self._run_session()
            except AuthError:
                raise
            except OrzChatConnectionError as exc:
                logger.warning("Could not connect: %s", exc)
                outcome = SessionOutcome(SessionResult.CLOSED)
            except OrzChatClosed as exc:
                if exc.code == 4003:
                    raise self._auth_error() from exc
                logger.warning("%s", exc)
                outcome = SessionOutcome(SessionResult.CLOSED)
            except OrzChatError as exc:
                logger.warning("OrzChat error: %s", exc)
                outcome = SessionOutcome(SessionResult.CLOSED)
            except OSError as exc:
                logger.warning("Network error: %s", exc)
                outcome = SessionOutcome(SessionResult.CLOSED)

            if outcome.connected:
                delay = self._settings.reconnect_initial
            if outcome.result is SessionResult.STOPPED or self._stop.is_set():
                break
            if outcome.matched and self._settings.once:
                logger.info("Ending after the first chat (--once).")
                break
            if outcome.result is SessionResult.PARTNER_LEFT:
                delay = self._settings.reconnect_initial
                logger.info("Finding another partner...")
                await self._sleep(0.75)
            else:
                logger.info("Reconnecting in %.1fs...", delay)
                await self._sleep(delay)
                delay = min(delay * 2, self._settings.reconnect_max)

    async def stop(self) -> None:
        """Stop the run loop and close the current connection."""
        self._stop.set()
        client = self._client
        if client is not None:
            await client.close()

    async def _run_session(self) -> SessionOutcome:
        client = self._client_factory()
        self._client = client
        matched = False
        connected = False
        worker: asyncio.Task[None] | None = None

        try:
            try:
                await client.connect()
            except (OrzChatConnectionError, OrzChatClosed):
                if self._stop.is_set():
                    return SessionOutcome(SessionResult.STOPPED)
                raise

            connected = True
            logger.info("Joined %s.", self._room_label())
            conversation = Conversation(
                system_prompt=self._settings.system_prompt,
                max_exchanges=self._settings.max_history,
            )
            inbox: asyncio.Queue[str] = asyncio.Queue(maxsize=32)
            matched_event = asyncio.Event()
            worker = asyncio.create_task(
                self._reply_worker(client, inbox, matched_event, conversation),
                name="orzchat-reply-worker",
            )

            try:
                async for event in client.events():
                    if event.type == "waiting":
                        logger.info("Waiting for a partner in %s...", self._room_label())
                    elif event.type == "matched":
                        matched = True
                        conversation.reset()
                        matched_event.set()
                        logger.info("Matched with a partner.")
                    elif event.type == "partner_disconnected":
                        logger.info("Partner disconnected.")
                        return SessionOutcome(SessionResult.PARTNER_LEFT, matched, connected)
                    elif event.type == "message":
                        text = event.text
                        if not text or not text.strip():
                            continue
                        logger.info("Incoming: %s", self._preview(text))
                        if inbox.full():
                            logger.warning("Incoming queue is full; dropping the oldest message.")
                            try:
                                inbox.get_nowait()
                            except asyncio.QueueEmpty:
                                pass
                        await inbox.put(text)
                    elif event.type == "error":
                        message = event.message or "unknown error"
                        logger.error("OrzChat server error: %s", message)
                        if _looks_like_auth_error(message):
                            raise self._auth_error()
                    else:
                        logger.debug("Ignoring OrzChat event type %r.", event.type)
            except OrzChatClosed as exc:
                if self._stop.is_set():
                    return SessionOutcome(SessionResult.STOPPED, matched, connected)
                raise

            return SessionOutcome(SessionResult.CLOSED, matched, connected)
        finally:
            if worker is not None:
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)
            await client.close()
            self._client = None

    async def _reply_worker(
        self,
        client: OrzChatClient,
        inbox: asyncio.Queue[str],
        matched_event: asyncio.Event,
        conversation: Conversation,
    ) -> None:
        reply_count = 0
        limit_warned = False

        while True:
            first = await inbox.get()
            await matched_event.wait()

            texts = [first]
            if self._settings.debounce_seconds > 0:
                # Give a partner who types several short lines in a row a
                # chance to finish before asking the model.
                await asyncio.sleep(self._settings.debounce_seconds)
                while True:
                    try:
                        texts.append(inbox.get_nowait())
                    except asyncio.QueueEmpty:
                        break

            user_text = "\n".join(part.strip() for part in texts if part.strip())
            if not user_text:
                continue

            if reply_count >= self._settings.max_replies_per_chat:
                if not limit_warned:
                    logger.warning(
                        "This chat reached the reply limit (%d); ignoring further messages.",
                        self._settings.max_replies_per_chat,
                    )
                    limit_warned = True
                continue

            if self._settings.dry_run:
                logger.info("Dry run: would reply to %s", preview(user_text))
                continue

            reply = await self._generate_reply(conversation, user_text)
            if reply is None:
                continue
            reply = fit_message(reply, self._settings.max_reply_chars)
            if not reply:
                continue

            if client.state is not ChatState.MATCHED:
                logger.debug("Skipping a reply because the partner is no longer connected.")
                continue
            try:
                await client.send_message(reply)
            except (OrzChatClosed, OrzChatStateError, ValueError) as exc:
                logger.debug("Could not send a reply: %s", exc)
                continue

            conversation.record_exchange(user_text, reply)
            reply_count += 1
            logger.info("Outgoing: %s", self._preview(reply))

    async def _generate_reply(self, conversation: Conversation, user_text: str) -> str | None:
        if self._llm is None:
            return None
        messages = conversation.build_messages(user_text)
        try:
            return await self._llm.complete(messages)
        except asyncio.CancelledError:
            raise
        except LLMError as exc:
            logger.error("Could not generate a reply: %s", exc)
            return None
        except Exception:
            logger.exception("Unexpected error while generating a reply.")
            return None

    def _make_client(self) -> OrzChatClient:
        return OrzChatClient(
            self._settings.room_id,
            server_url=self._settings.server_url,
            auth_salt=self._settings.auth_salt,
            proxy=self._settings.proxy,
            max_message_chars=self._settings.max_reply_chars,
        )

    def _room_label(self) -> str:
        if self._settings.room_id:
            return f"room {self._settings.room_id!r}"
        return "the public queue"

    def _preview(self, text: str) -> str:
        if not self._settings.log_messages:
            return f"<{len(text)} characters hidden>"
        return preview(text)

    async def _sleep(self, delay: float) -> None:
        if delay <= 0:
            return
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=delay)
        except TimeoutError:
            pass

    @staticmethod
    def _auth_error() -> AuthError:
        return AuthError(
            "OrzChat rejected the join authorization. The site's client salt may "
            "have changed; update ORZCHAT_AUTH_SALT or pass --auth-salt."
        )


def _looks_like_auth_error(message: str | None) -> bool:
    normalized = (message or "").casefold()
    return any(
        token in normalized
        for token in ("unauthorized", "forbidden", "not authorized", "authentication failed")
    )
