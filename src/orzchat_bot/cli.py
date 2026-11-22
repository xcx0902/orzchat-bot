"""Command-line entry point for the OrzChat bot."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from dotenv import load_dotenv

from . import __version__
from .bot import AuthError, Bot, BotError
from .config import ConfigurationError, Settings, normalize_room_id
from .llm import ChatCompletionClient, LLMError

logger = logging.getLogger(__name__)

_UNSET = object()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orzchat-bot",
        description=(
            "Join an OrzChat room and reply to messages with an OpenAI-compatible "
            "Chat Completions model."
        ),
        epilog=(
            "Environment variables are read from the process and from a .env file "
            "(see .env.example). Command-line options override them."
        ),
    )
    parser.add_argument(
        "room",
        nargs="?",
        default=None,
        help="Room name; omit it for the public matchmaking queue.",
    )
    parser.add_argument("--model", help="Chat Completions model ID (OPENAI_MODEL).")
    parser.add_argument("--api-key", help="Provider API key (OPENAI_API_KEY).")
    parser.add_argument(
        "--base-url",
        help="OpenAI-compatible API base URL, usually ending in /v1 (OPENAI_BASE_URL).",
    )
    parser.add_argument(
        "--api-proxy",
        metavar="URL|none",
        help="Proxy for Chat Completions calls, or 'none' (OPENAI_PROXY).",
    )
    parser.add_argument(
        "--system-prompt",
        help="Persona/system prompt (BOT_SYSTEM_PROMPT).",
    )
    parser.add_argument(
        "--system-prompt-file",
        metavar="PATH",
        help="Read the persona/system prompt from a UTF-8 file.",
    )
    parser.add_argument(
        "--hello-message",
        metavar="TEXT",
        help=(
            "Send this message immediately after matching, before any incoming "
            "message (BOT_HELLO_MESSAGE). An empty value disables it."
        ),
    )
    parser.add_argument(
        "--temperature",
        type=_parse_temperature,
        default=_UNSET,
        metavar="FLOAT|none",
        help="Sampling temperature, or 'none' to omit it (OPENAI_TEMPERATURE).",
    )
    parser.add_argument(
        "--max-tokens",
        type=_positive_int,
        default=_UNSET,
        metavar="N",
        help="Optional max_tokens value (OPENAI_MAX_TOKENS).",
    )
    parser.add_argument(
        "--max-history",
        type=_non_negative_int,
        default=None,
        metavar="N",
        help="Completed exchanges to include in context (BOT_MAX_HISTORY, default 10).",
    )
    parser.add_argument(
        "--max-reply-chars",
        type=_positive_int,
        default=None,
        metavar="N",
        help="Maximum outgoing message length, up to 300 (BOT_MAX_REPLY_CHARS).",
    )
    parser.add_argument(
        "--debounce",
        type=_non_negative_float,
        default=None,
        metavar="SECONDS",
        help="Wait this long for follow-up messages before replying (BOT_DEBOUNCE_SECONDS).",
    )
    parser.add_argument(
        "--max-replies-per-chat",
        type=_positive_int,
        default=None,
        metavar="N",
        help="Safety cap on replies to one partner (BOT_MAX_REPLIES_PER_CHAT).",
    )
    parser.add_argument(
        "--request-timeout",
        type=_positive_float,
        default=None,
        metavar="SECONDS",
        help="Chat Completions request timeout (OPENAI_TIMEOUT).",
    )
    parser.add_argument("--server-url", help="OrzChat WebSocket URL (ORZCHAT_SERVER_URL).")
    parser.add_argument(
        "--auth-salt",
        help="Join authorization salt, if OrzChat rotates it (ORZCHAT_AUTH_SALT).",
    )
    parser.add_argument(
        "--proxy",
        metavar="URL|none",
        help="WebSocket proxy URL, or 'none' to force a direct connection (ORZCHAT_PROXY).",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity (BOT_LOG_LEVEL).",
    )
    parser.add_argument(
        "--log-messages",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Include chat text in logs (BOT_LOG_MESSAGES).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="Connect and log incoming messages without calling the model.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        default=None,
        help="Exit after the first chat instead of finding another partner.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        settings = _apply_cli(Settings.from_env(), args)
        settings.validate()
    except ConfigurationError as exc:
        parser.error(str(exc))
        raise AssertionError("argparse.error() always exits") from exc

    _configure_logging(settings.log_level)
    logger.info("OrzChat bot %s starting.", __version__)
    logger.info("Room: %s", settings.room_id or "public queue")
    logger.info("Server: %s", settings.server_url)
    if settings.dry_run:
        logger.info("Dry run: incoming messages are logged but not answered.")
    else:
        logger.info("Model: %s via %s", settings.model, settings.base_url)
    logger.info("Press Ctrl+C to stop.")

    try:
        return asyncio.run(_run(settings))
    except KeyboardInterrupt:
        logger.info("Interrupted.")
        return 130
    except AuthError as exc:
        logger.error("%s", exc)
        return 3
    except LLMError as exc:
        logger.error("%s", exc)
        return 2
    except BotError as exc:
        logger.error("%s", exc)
        return 1
    except ConfigurationError as exc:
        logger.error("%s", exc)
        return 2


def _apply_cli(settings: Settings, args: argparse.Namespace) -> Settings:
    changes: dict[str, object] = {}

    if args.room is not None:
        changes["room_id"] = normalize_room_id(args.room)
    for attribute, key in (
        ("model", "model"),
        ("api_key", "api_key"),
        ("base_url", "base_url"),
        ("server_url", "server_url"),
        ("auth_salt", "auth_salt"),
        ("max_history", "max_history"),
        ("max_reply_chars", "max_reply_chars"),
        ("debounce", "debounce_seconds"),
        ("max_replies_per_chat", "max_replies_per_chat"),
        ("request_timeout", "timeout"),
        ("log_level", "log_level"),
    ):
        value = getattr(args, attribute)
        if value is not None:
            changes[key] = value

    if args.temperature is not _UNSET:
        changes["temperature"] = args.temperature
    if args.max_tokens is not _UNSET:
        changes["max_tokens"] = args.max_tokens
    if args.hello_message is not None:
        changes["hello_message"] = args.hello_message.strip() or None
    if args.log_messages is not None:
        changes["log_messages"] = args.log_messages
    if args.dry_run is not None:
        changes["dry_run"] = args.dry_run
    if args.once is not None:
        changes["once"] = args.once
    if args.proxy is not None:
        changes["proxy"] = _parse_proxy(args.proxy, "--proxy")
    if args.api_proxy is not None:
        changes["api_proxy"] = _parse_proxy(args.api_proxy, "--api-proxy")

    if args.system_prompt_file:
        if args.system_prompt:
            raise ConfigurationError(
                "Use either --system-prompt or --system-prompt-file, not both."
            )
        try:
            prompt = Path(args.system_prompt_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConfigurationError(f"Could not read --system-prompt-file: {exc}") from exc
        if not prompt:
            raise ConfigurationError("--system-prompt-file is empty.")
        changes["system_prompt"] = prompt
    elif args.system_prompt is not None:
        changes["system_prompt"] = args.system_prompt.strip()

    return replace(settings, **changes)  # type: ignore[arg-type]


async def _run(settings: Settings) -> int:
    llm: ChatCompletionClient | None = None
    if not settings.dry_run:
        llm = ChatCompletionClient(
            base_url=settings.base_url,
            api_key=settings.api_key,
            model=settings.model,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
            timeout=settings.timeout,
            api_proxy=settings.api_proxy,
            extra_body=settings.extra_body,
            extra_headers=settings.extra_headers,
        )

    bot = Bot(settings, llm=llm)
    loop = asyncio.get_running_loop()
    stop_tasks: set[asyncio.Task[None]] = set()

    def request_stop() -> None:
        logger.info("Stopping...")
        task = asyncio.create_task(bot.stop())
        stop_tasks.add(task)
        task.add_done_callback(stop_tasks.discard)

    installed: list[signal.Signals] = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_stop)
            installed.append(sig)
        except (NotImplementedError, RuntimeError):
            # Windows and some embedded loops do not support this; Ctrl+C
            # still reaches asyncio.run() as KeyboardInterrupt.
            pass

    try:
        await bot.run()
    finally:
        await bot.stop()
        if llm is not None:
            await llm.close()
        for sig in installed:
            loop.remove_signal_handler(sig)
    return 0


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    for noisy in ("httpx", "httpcore", "openai", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _parse_temperature(value: str) -> float | None:
    if value.strip().lower() in {"none", "null", "off"}:
        return None
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a number or 'none'") from None
    if not 0.0 <= number <= 2.0:
        raise argparse.ArgumentTypeError("must be between 0 and 2")
    return number


def _parse_proxy(value: str, option: str) -> str | None:
    text = value.strip()
    if text.lower() in {"", "none", "off", "direct"}:
        return None
    if not text.startswith(("http://", "https://")):
        raise ConfigurationError(f"{option} must be an http:// or https:// URL, or 'none'.")
    return text


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an integer") from None
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def _non_negative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an integer") from None
    if number < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return number


def _positive_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a number") from None
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def _non_negative_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a number") from None
    if number < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return number


if __name__ == "__main__":
    raise SystemExit(main())
