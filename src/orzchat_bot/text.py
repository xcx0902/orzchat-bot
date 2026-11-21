"""Text normalization and message-size helpers."""

from __future__ import annotations

import re

# Control characters other than tab and newline.  They are not useful in a
# chat message and may upset a provider or the OrzChat server.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """Normalize line endings and whitespace without changing wording."""
    if not isinstance(text, str):
        raise TypeError("text must be a string.")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_CHARS.sub("", text)
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = _EXCESS_BLANK_LINES.sub("\n\n", text)
    return text.strip()


def fit_message(text: str, limit: int = 300) -> str:
    """Return one chat-safe message no longer than ``limit`` characters.

    OrzChat's web client caps outgoing messages at 300 characters.  Long model
    replies are cut at a natural boundary (paragraph, line, sentence, or word)
    and marked with an ellipsis rather than being sent as several messages.
    """
    if limit < 1:
        raise ValueError("limit must be positive.")
    text = normalize_text(text)
    if len(text) <= limit:
        return text

    window = text[:limit]
    cut = -1
    for separator in ("\n\n", "\n", ". ", "! ", "? ", "; ", " "):
        index = window.rfind(separator)
        if index >= limit // 2:
            cut = index + len(separator)
            break
    if cut < 0:
        cut = limit

    clipped = window[:cut].rstrip()
    if len(clipped) >= limit:
        clipped = clipped[: limit - 1].rstrip()
    return clipped + "\u2026"


def preview(text: str, width: int = 180) -> str:
    """Return a short, log-safe representation of a message."""
    if width < 1:
        raise ValueError("width must be positive.")
    normalized = normalize_text(text)
    if len(normalized) > width:
        normalized = normalized[: width - 1].rstrip() + "\u2026"
    return repr(normalized)
