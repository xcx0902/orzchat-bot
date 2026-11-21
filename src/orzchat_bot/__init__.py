"""An OpenAI-compatible chat bot for orzchat.com."""

from __future__ import annotations

from .bot import AuthError, Bot, BotError
from .client import (
    ChatEvent,
    ChatState,
    OrzChatClient,
    OrzChatClosed,
    OrzChatConnectionError,
    OrzChatError,
    OrzChatProtocolError,
    OrzChatStateError,
)
from .config import ConfigurationError, Settings
from .llm import ChatCompletionClient, LLMError

__version__ = "0.1.0"

__all__ = [
    "AuthError",
    "Bot",
    "BotError",
    "ChatCompletionClient",
    "ChatEvent",
    "ChatState",
    "ConfigurationError",
    "LLMError",
    "OrzChatClient",
    "OrzChatClosed",
    "OrzChatConnectionError",
    "OrzChatError",
    "OrzChatProtocolError",
    "OrzChatStateError",
    "Settings",
    "__version__",
]
