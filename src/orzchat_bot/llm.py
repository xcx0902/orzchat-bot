"""OpenAI-compatible Chat Completions client."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import httpx
from openai import AsyncOpenAI, OpenAIError


class LLMError(RuntimeError):
    """A Chat Completions request failed or returned no usable text."""


class ChatCompletionClient:
    """Thin async wrapper around an OpenAI-compatible endpoint.

    Any provider that implements ``POST /chat/completions`` works: OpenAI,
    OpenRouter, Together, Groq, vLLM, Ollama, LM Studio, and so on.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float | None = 0.8,
        max_tokens: int | None = None,
        timeout: float = 60.0,
        max_retries: int = 2,
        api_proxy: str | None = None,
        extra_body: Mapping[str, Any] | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.extra_body = dict(extra_body) if extra_body else None
        # ``trust_env=False`` avoids two common surprises: a dead ambient
        # proxy breaking local providers, and malformed NO_PROXY entries
        # crashing httpx.  Pass OPENAI_PROXY / --api-proxy to use a proxy.
        try:
            self._http_client = httpx.AsyncClient(
                trust_env=False,
                proxy=api_proxy,
                timeout=httpx.Timeout(timeout),
                follow_redirects=True,
            )
            self._client = AsyncOpenAI(
                base_url=base_url,
                api_key=api_key,
                timeout=timeout,
                max_retries=max_retries,
                http_client=self._http_client,
                default_headers=dict(extra_headers) if extra_headers else None,
            )
        except (OpenAIError, ValueError, httpx.InvalidURL, httpx.HTTPError) as exc:
            raise LLMError(f"Could not configure the Chat Completions client: {exc}") from exc

    async def complete(self, messages: Sequence[Mapping[str, str]]) -> str:
        """Return the model's reply text for a ``messages`` array."""
        request: dict[str, Any] = {
            "model": self.model,
            "messages": [dict(message) for message in messages],
        }
        if self.temperature is not None:
            request["temperature"] = self.temperature
        if self.max_tokens is not None:
            request["max_tokens"] = self.max_tokens
        if self.extra_body is not None:
            request["extra_body"] = self.extra_body

        try:
            completion = await self._client.chat.completions.create(**request)
        except OpenAIError as exc:
            raise LLMError(f"Chat Completions request failed: {exc}") from exc

        if not completion.choices:
            raise LLMError("The Chat Completions response contained no choices.")
        text = _message_text(completion.choices[0].message)
        if not text:
            raise LLMError("The Chat Completions response contained an empty message.")
        return text

    async def close(self) -> None:
        await self._client.close()
        await self._http_client.aclose()

    async def __aenter__(self) -> ChatCompletionClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


def _message_text(message: object) -> str:
    """Extract text from a string or multipart message content."""
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for part in content:
        if isinstance(part, str):
            parts.append(part)
            continue
        text = getattr(part, "text", None)
        if isinstance(text, str):
            parts.append(text)
        elif isinstance(part, Mapping) and isinstance(part.get("text"), str):
            parts.append(part["text"])
    return "".join(parts).strip()
