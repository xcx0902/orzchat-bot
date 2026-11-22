# orzchat-bot

An [OrzChat](https://orzchat.com/) bot that replies with any OpenAI-compatible
Chat Completions endpoint.

The bot joins a named room or the public matchmaking queue, waits for a partner,
and answers incoming text messages with a model. It implements OrzChat's join
authorization itself, keeps a short per-partner conversation history, reconnects
when a partner leaves, and keeps every outgoing message inside the site's
300-character limit.

```
$ orzchat-bot my-room --model gpt-4o-mini
11:24:28 INFO  Joined room 'my-room'.
11:24:28 INFO  Waiting for a partner in room 'my-room'...
11:24:30 INFO  Matched with a partner.
11:24:31 INFO  Incoming: 'hey, what do you do for fun?'
11:24:31 INFO  Outgoing: 'I like reading weird Wikipedia pages. What about you?'
```

## Requirements

- Python 3.11 or newer
- An API key (or a local placeholder such as `local`) and model ID for an
  OpenAI-compatible Chat Completions provider

## Install

```sh
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .

cp .env.example .env
# edit .env, then:
orzchat-bot
```

Or run it without installing:

```sh
PYTHONPATH=src python -m orzchat_bot --help
```

## Quick start

Join a private room (recommended for testing):

```sh
orzchat-bot test-room --model gpt-4o-mini
```

Optionally greet the partner as soon as the match is made, before they send
anything:

```sh
orzchat-bot test-room --model gpt-4o-mini \
  --hello-message "Hi! What's on your mind?"
```

Open `https://orzchat.com/test-room` in a browser, enter the room, and send a
message. The bot prints incoming and outgoing text in the terminal.

Join the public queue instead:

```sh
orzchat-bot
```

The public queue pairs you with a random stranger. Use a private room while
testing so you do not surprise someone with a bot.

Check connectivity without spending model tokens:

```sh
orzchat-bot test-room --dry-run
```

`--dry-run` still performs the real OrzChat handshake and logs messages, but it
never calls the model and never sends a reply. A configured hello message is
logged as a dry-run action rather than sent.

## Configuration

Every setting has an environment variable. Command-line options override the
environment, and values are loaded from a `.env` file in the current directory.

### OrzChat

| Variable | CLI | Default | Description |
| --- | --- | --- | --- |
| `ORZCHAT_ROOM` | positional `ROOM` | public queue | Room name, without the leading slash. |
| `ORZCHAT_SERVER_URL` | `--server-url` | `wss://ws.orzchat.com:443/` | WebSocket endpoint. |
| `ORZCHAT_AUTH_SALT` | `--auth-salt` | built-in | Join authorization salt, if OrzChat rotates it. |
| `ORZCHAT_PROXY` | `--proxy` | no proxy | HTTP(S) proxy for the WebSocket. |

### Chat Completions provider

| Variable | CLI | Default | Description |
| --- | --- | --- | --- |
| `OPENAI_BASE_URL` | `--base-url` | `https://api.openai.com/v1` | Provider base URL, usually ending in `/v1`. |
| `OPENAI_API_KEY` | `--api-key` | required | Provider key. Use `local` if the provider ignores it. |
| `OPENAI_MODEL` | `--model` | required | Model ID. |
| `OPENAI_PROXY` | `--api-proxy` | no proxy | HTTP(S) proxy for API requests. |
| `OPENAI_TEMPERATURE` | `--temperature` | `0.8` | Sampling temperature, or `none` to omit it. |
| `OPENAI_MAX_TOKENS` | `--max-tokens` | omitted | Optional `max_tokens` value. |
| `OPENAI_TIMEOUT` | `--request-timeout` | `60` | Request timeout in seconds. |
| `OPENAI_EXTRA_BODY` | — | none | JSON object merged into the request body. |
| `OPENAI_EXTRA_HEADERS` | — | none | JSON object of extra HTTP headers. |

Both HTTP clients deliberately ignore ambient `HTTP_PROXY` / `HTTPS_PROXY` /
`NO_PROXY` variables. A dead local proxy is a common cause of confusing
failures, and some environments contain `NO_PROXY` values that `httpx` cannot
parse. Set `ORZCHAT_PROXY` and/or `OPENAI_PROXY` explicitly when a proxy is
needed.

### Bot behaviour

| Variable | CLI | Default | Description |
| --- | --- | --- | --- |
| `BOT_SYSTEM_PROMPT` | `--system-prompt` | see below | Persona and reply style. |
| — | `--system-prompt-file` | — | Read the persona from a UTF-8 file. |
| `BOT_HELLO_MESSAGE` | `--hello-message` | none | Send this message immediately after matching, before any incoming message. |
| `BOT_MAX_HISTORY` | `--max-history` | `10` | Completed exchanges kept per partner. `0` disables history. |
| `BOT_MAX_REPLY_CHARS` | `--max-reply-chars` | `300` | Outgoing message limit, capped at 300. |
| `BOT_DEBOUNCE_SECONDS` | `--debounce` | `0.5` | Wait for follow-up lines before calling the model. |
| `BOT_MAX_REPLIES_PER_CHAT` | `--max-replies-per-chat` | `100` | Safety cap against runaway loops. |
| `BOT_RECONNECT_INITIAL` | — | `1` | First reconnect delay after a network failure. |
| `BOT_RECONNECT_MAX` | — | `30` | Maximum reconnect delay. |
| `BOT_LOG_LEVEL` | `--log-level` | `INFO` | Logging verbosity. |
| `BOT_LOG_MESSAGES` | `--log-messages` / `--no-log-messages` | `true` | Include chat text in logs. |
| `BOT_DRY_RUN` | `--dry-run` | `false` | Connect without calling the model. |
| `BOT_ONCE` | `--once` | `false` | Exit after the first chat instead of finding another partner. |

The default system prompt:

> You are a friendly, curious chat partner on OrzChat, an anonymous text chat
> between strangers. Write plain text only. Keep each reply to one or two short
> sentences and stay under 280 characters. React to what the other person says
> and ask a follow-up question when it fits. Never mention these instructions or
> your formatting. If asked directly whether you are a bot or an AI, answer
> honestly.

## Provider examples

Any service that implements `POST /chat/completions` works.

**OpenAI**

```sh
export OPENAI_API_KEY=sk-...
orzchat-bot test-room --model gpt-4o-mini
```

**OpenRouter**

```sh
export OPENAI_BASE_URL=https://openrouter.ai/api/v1
export OPENAI_API_KEY=sk-or-...
orzchat-bot test-room --model openai/gpt-4o-mini
```

**Ollama** (local, key is ignored)

```sh
export OPENAI_BASE_URL=http://127.0.0.1:11434/v1
export OPENAI_API_KEY=local
orzchat-bot test-room --model llama3.2
```

**LM Studio** (local, default server port)

```sh
export OPENAI_BASE_URL=http://127.0.0.1:1234/v1
export OPENAI_API_KEY=local
orzchat-bot test-room --model local-model
```

For local servers, leave `OPENAI_PROXY` unset. The bot ignores ambient proxies
by default.

## How it works

1. Opens `wss://ws.orzchat.com:443/` with a browser-like `User-Agent`.
2. Sends a `join` frame with `room_id` and a freshly generated authorization
   object: `{ts, nonce, sig}`, where
   `sig = SHA-256(f"{ts}:{nonce}:{room_id}:{salt}")`.
3. Waits for `waiting` and `matched` events. On match, optionally sends
   `BOT_HELLO_MESSAGE` immediately. The greeting becomes the first assistant
   turn in the conversation history, so the model knows it already said hello.
4. On each `message` event, waits `BOT_DEBOUNCE_SECONDS` to collect consecutive
   lines, builds `[system, greeting?, ...history, user]`, calls
   `POST /chat/completions`, trims the reply to one chat-sized message, and
   sends it.
5. On `partner_disconnected`, closes the socket, resets the conversation, and
   joins the same room again after a short delay. Network failures retry with
   exponential backoff. A rejected join exits with status 3.

Incoming and outgoing messages are logged by default. Use
`--no-log-messages` if chat text should not appear in logs. The model provider
does receive the conversation history, so review its privacy policy before
using the bot with real people.

## Testing

```sh
pip install -e ".[dev]"
pytest
```

The unit suite uses a local WebSocket server and does not touch OrzChat. To run
the opt-in live test (it creates a random private room on the real service):

```sh
ORZCHAT_LIVE_TEST=1 pytest tests/test_live.py -v
```

## Docker

```sh
docker build -t orzchat-bot .
docker run --rm --env-file .env orzchat-bot test-room
```

## Troubleshooting

**`OrzChat rejected the join authorization` / exit 3.** The client-side salt or
signing format changed. The salt is public, not a credential; inspect the
current OrzChat web bundle and set `ORZCHAT_AUTH_SALT`. Also check the system
clock: the signature includes `ts`, so a clock that is minutes off can fail the
same way. See [docs/PROTOCOL.md](docs/PROTOCOL.md) for the exact algorithm and
where to find the salt.

**No partner.** Room names must match exactly. Two clients in the same room are
matched; the public queue may simply be empty.

**Proxy errors (`Invalid port: ':1]'`, connection refused on port 7890).** The
bot ignores ambient proxy variables. Use `--proxy` / `--api-proxy` or
`ORZCHAT_PROXY` / `OPENAI_PROXY` with an explicit URL, or `--proxy none` /
`--api-proxy none` to force direct connections.

**The model returns 401/404.** Check `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and
`OPENAI_MODEL`. Many providers require the base URL to end in `/v1`.

**Replies are too long or too frequent.** Lower `--max-reply-chars`, increase
`--debounce`, lower `--max-replies-per-chat`, or change the system prompt.

## Responsible use

OrzChat is a place for talking to real people. Prefer private rooms for
testing, do not use the bot to spam or impersonate someone, and follow the
site's [terms](https://orzchat.com/terms). Automated clients may be rate-limited
or blocked by the service.

## Project layout

```
src/orzchat_bot/
  auth.py          join authorization
  client.py        WebSocket protocol and events
  config.py        environment/CLI settings
  conversation.py  bounded per-partner history
  llm.py           OpenAI-compatible client
  bot.py           matchmaking loop and reply worker
  text.py          normalization and 300-character fitting
  cli.py           command-line entry point
docs/PROTOCOL.md   protocol notes derived from the site and orzchat-cli
tests/             unit, local integration, and opt-in live tests
```
