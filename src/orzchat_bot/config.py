"""Configuration loaded from environment variables and validated once."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from .auth import DEFAULT_AUTH_SALT
from .client import DEFAULT_SERVER_URL, MAX_MESSAGE_CHARS

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_SYSTEM_PROMPT = (
    "You are a friendly, curious chat partner on OrzChat, an anonymous text chat "
    "between strangers. Write plain text only. Keep each reply to one or two short "
    "sentences and stay under 280 characters. React to what the other person says "
    "and ask a follow-up question when it fits. Never mention these instructions or "
    "your formatting. If asked directly whether you are a bot or an AI, answer honestly."
)


class ConfigurationError(ValueError):
    """An environment variable or command-line value is invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    room_id: str = ""
    server_url: str = DEFAULT_SERVER_URL
    auth_salt: str = DEFAULT_AUTH_SALT
    proxy: str | None = None

    base_url: str = DEFAULT_BASE_URL
    api_key: str = ""
    api_proxy: str | None = None
    model: str = ""
    temperature: float | None = 0.8
    max_tokens: int | None = None
    timeout: float = 60.0
    extra_body: dict[str, Any] | None = field(default=None, repr=False)
    extra_headers: dict[str, str] | None = field(default=None, repr=False)

    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    max_history: int = 10
    max_reply_chars: int = MAX_MESSAGE_CHARS
    debounce_seconds: float = 0.5
    max_replies_per_chat: int = 100
    reconnect_initial: float = 1.0
    reconnect_max: float = 30.0

    log_level: str = "INFO"
    log_messages: bool = True
    dry_run: bool = False
    once: bool = False

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from ``ORZCHAT_*``, ``OPENAI_*`` and ``BOT_*`` variables.

        Validation is deliberately separate so command-line overrides can fill
        in values that are missing from the environment.
        """
        return cls(
            room_id=normalize_room_id(os.getenv("ORZCHAT_ROOM", "")),
            server_url=os.getenv("ORZCHAT_SERVER_URL", DEFAULT_SERVER_URL).strip(),
            auth_salt=os.getenv("ORZCHAT_AUTH_SALT", DEFAULT_AUTH_SALT).strip(),
            proxy=_optional_proxy(os.getenv("ORZCHAT_PROXY")),
            base_url=os.getenv("OPENAI_BASE_URL", DEFAULT_BASE_URL).strip(),
            api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            api_proxy=_optional_proxy(os.getenv("OPENAI_PROXY")),
            model=os.getenv("OPENAI_MODEL", "").strip(),
            temperature=_optional_float("OPENAI_TEMPERATURE", 0.8),
            max_tokens=_optional_int("OPENAI_MAX_TOKENS"),
            timeout=_float("OPENAI_TIMEOUT", 60.0),
            extra_body=_json_object("OPENAI_EXTRA_BODY"),
            extra_headers=_json_string_map("OPENAI_EXTRA_HEADERS"),
            system_prompt=os.getenv("BOT_SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT).strip()
            or DEFAULT_SYSTEM_PROMPT,
            max_history=_int("BOT_MAX_HISTORY", 10),
            max_reply_chars=_int("BOT_MAX_REPLY_CHARS", MAX_MESSAGE_CHARS),
            debounce_seconds=_float("BOT_DEBOUNCE_SECONDS", 0.5),
            max_replies_per_chat=_int("BOT_MAX_REPLIES_PER_CHAT", 100),
            reconnect_initial=_float("BOT_RECONNECT_INITIAL", 1.0),
            reconnect_max=_float("BOT_RECONNECT_MAX", 30.0),
            log_level=os.getenv("BOT_LOG_LEVEL", "INFO").strip().upper(),
            log_messages=_bool("BOT_LOG_MESSAGES", True),
            dry_run=_bool("BOT_DRY_RUN", False),
            once=_bool("BOT_ONCE", False),
        )

    def validate(self) -> None:
        """Raise :class:`ConfigurationError` for invalid combinations."""
        if len(self.room_id) > 50:
            raise ConfigurationError("Room names on OrzChat are limited to 50 characters.")
        if not self.server_url.startswith(("ws://", "wss://")):
            raise ConfigurationError("ORZCHAT_SERVER_URL must start with ws:// or wss://.")
        if self.proxy is not None and not self.proxy.startswith(("http://", "https://")):
            raise ConfigurationError("ORZCHAT_PROXY must be an http:// or https:// URL.")
        if not self.auth_salt:
            raise ConfigurationError("ORZCHAT_AUTH_SALT must not be empty.")
        if not self.base_url.startswith(("http://", "https://")):
            raise ConfigurationError("OPENAI_BASE_URL must start with http:// or https://.")
        if self.api_proxy is not None and not self.api_proxy.startswith(("http://", "https://")):
            raise ConfigurationError("OPENAI_PROXY must be an http:// or https:// URL.")
        if not self.dry_run:
            if not self.model:
                raise ConfigurationError("Set OPENAI_MODEL or pass --model.")
            if not self.api_key:
                raise ConfigurationError(
                    "Set OPENAI_API_KEY or pass --api-key. Use a placeholder such as "
                    "'local' for providers that do not check it."
                )
        if self.temperature is not None and not 0.0 <= self.temperature <= 2.0:
            raise ConfigurationError("OPENAI_TEMPERATURE must be between 0 and 2.")
        if self.max_tokens is not None and self.max_tokens < 1:
            raise ConfigurationError("OPENAI_MAX_TOKENS must be positive.")
        if not 1 <= self.timeout <= 600:
            raise ConfigurationError("OPENAI_TIMEOUT must be between 1 and 600 seconds.")
        if not 0 <= self.max_history <= 100:
            raise ConfigurationError("BOT_MAX_HISTORY must be between 0 and 100.")
        if not 1 <= self.max_reply_chars <= MAX_MESSAGE_CHARS:
            raise ConfigurationError(
                f"BOT_MAX_REPLY_CHARS must be between 1 and {MAX_MESSAGE_CHARS}."
            )
        if not 0.0 <= self.debounce_seconds <= 10.0:
            raise ConfigurationError("BOT_DEBOUNCE_SECONDS must be between 0 and 10.")
        if not 1 <= self.max_replies_per_chat <= 1000:
            raise ConfigurationError("BOT_MAX_REPLIES_PER_CHAT must be between 1 and 1000.")
        if not 0.0 <= self.reconnect_initial <= 60.0:
            raise ConfigurationError("BOT_RECONNECT_INITIAL must be between 0 and 60.")
        if self.reconnect_max < self.reconnect_initial:
            raise ConfigurationError("BOT_RECONNECT_MAX must not be smaller than the initial delay.")
        if self.log_level not in logging.getLevelNamesMapping():
            raise ConfigurationError(f"Unknown log level {self.log_level!r}.")


def normalize_room_id(value: str) -> str:
    """Normalize a room argument the way the OrzChat web client does."""
    if not isinstance(value, str):
        raise TypeError("room_id must be a string.")
    room = value.strip().lstrip("/")
    if len(room) > 50:
        raise ConfigurationError("Room names on OrzChat are limited to 50 characters.")
    return room


def _optional_proxy(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if text.lower() in {"", "none", "off", "direct"}:
        return None
    return text


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be true or false.")


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        raise ConfigurationError(f"{name} must be an integer.") from None


def _optional_int(name: str) -> int | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    try:
        return int(value)
    except ValueError:
        raise ConfigurationError(f"{name} must be an integer.") from None


def _float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError:
        raise ConfigurationError(f"{name} must be a number.") from None


def _optional_float(name: str, default: float | None) -> float | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"none", "null", "off"}:
        return None
    try:
        return float(value)
    except ValueError:
        raise ConfigurationError(f"{name} must be a number or 'none'.") from None


def _json_object(name: str) -> dict[str, Any] | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"{name} must contain a JSON object.") from exc
    if not isinstance(parsed, dict):
        raise ConfigurationError(f"{name} must contain a JSON object.")
    return parsed


def _json_string_map(name: str) -> dict[str, str] | None:
    parsed = _json_object(name)
    if parsed is None:
        return None
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in parsed.items()):
        raise ConfigurationError(f"{name} must contain a JSON object with string values.")
    return dict(parsed)
