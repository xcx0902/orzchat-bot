# OrzChat WebSocket protocol notes

These notes describe the protocol implemented by `orzchat-bot`. They were
derived from the public OrzChat web bundle, the `orzchat-cli` npm package
(version 0.2.2), and live observations on 2026-11-21. Neither the HTTP API nor
the WebSocket protocol is documented officially, so treat this as a moving
target.

## Endpoint

```
wss://ws.orzchat.com:443/
```

The server speaks JSON text frames. One WebSocket carries one matchmaking
session. After a partner disconnects, open a new socket and send a new `join`
frame; the server does not put the same socket back in the queue.

## Join and authorization

The first client frame must be a `join`:

```json
{
  "type": "join",
  "room_id": "my-room",
  "auth": {
    "ts": 1795230905196,
    "nonce": "ocffmocenak7gfqv",
    "sig": "fd10b401699752c78175802fe60fecd1203da9cc6a8967ad52f1e04f2a20882f"
  }
}
```

- `room_id` is `""` for the public queue, or the room name without a leading
  slash. The web client rejects room paths longer than 50 characters.
- `ts` is the current Unix time in milliseconds (`Date.now()` in JavaScript).
- `nonce` is 16 lowercase alphanumeric characters. The web client builds it
  from two `Math.random().toString(36).substring(2, 10)` calls.
- `sig` is the lowercase hex SHA-256 of:

  ```
  f"{ts}:{nonce}:{room_id}:{salt}"
  ```

The salt is embedded in OrzChat's public JavaScript bundle in an obfuscated
byte array:

```js
[53, 40, 32, 5, ...].map(byte => String.fromCharCode(90 ^ byte)).join("")
```

At the time of writing it decodes to:

```
orz_front_salt_3e8b1d9c2a7f5e0a6d4b8c9e1f2a3b4c
```

This is public client-side code, not a user credential. If the signature
algorithm or salt changes, the server replies with an `error` event
(`{"type": "error", "message": "Unauthorized"}`) and closes with code `4003`.
Set `ORZCHAT_AUTH_SALT` / `--auth-salt` after finding the new value in the
current bundle.

### Required headers

Live testing showed that the default Python `websockets` user agent is
rejected with `Unauthorized`, while a browser-like (or even `node`) user agent
is accepted. This bot sends:

```
User-Agent: Mozilla/5.0 ... orzchat-bot/0.1
Origin: https://orzchat.com
```

`Origin` was not required in testing, but sending the site's origin mirrors the
browser client. The bot deliberately disables ambient proxy environment
variables; pass `--proxy` / `ORZCHAT_PROXY` to use a proxy.

## Server events

| `type` | Fields | Meaning |
| --- | --- | --- |
| `waiting` | `message` | The socket is in the queue. |
| `matched` | `message` | A partner is connected; messages may now be sent. |
| `message` | `text` | Text from the partner. |
| `partner_disconnected` | `message` | The partner left; reconnect to find another. |
| `error` | `message` | Server-side error, for example `Unauthorized`. |

Representative sequence for two clients joining the same room:

```text
client A -> join
client A <- {"type":"waiting","message":"Waiting for a chat partner..."}

client B -> join
client B <- {"type":"matched","message":"You're now connected to a partner!"}
client A <- {"type":"matched","message":"You're now connected to a partner!"}

client B -> {"type":"message","text":"hello"}
client A <- {"type":"message","text":"hello"}

client B closes
client A <- {"type":"partner_disconnected","message":"Your partner has disconnected"}
```

Unknown event types carry their complete JSON object in `event.data`; the bot
logs and ignores them.

## Sending messages

After a `matched` event:

```json
{"type": "message", "text": "hello"}
```

The web client slices outgoing text with `.slice(0, 300)`, so the practical
limit is 300 characters. This bot enforces the same limit and trims long model
replies at a natural boundary with an ellipsis instead of splitting them into
several messages.

## Failure behavior

- `4003` close: the join authorization was rejected (or the room is forbidden).
- A normal close (1000/1001): the server ended the session.
- A network drop or 1006: reconnect with backoff.
- A partner leaving produces `partner_disconnected`; reconnect and join again.

## Relationship to orzchat-cli and orzchat-sdk

- `orzchat-cli` 0.2.2's `connection.js` sends
  `{"type":"join","room_id":roomId}` without an `auth` object. The hosted server
  currently requires browser-style authorization, so this bot uses the web
  client's scheme instead.
- The Python `orzchat-sdk` exposes `auth_provider`, a callable returning the
  authorization mapping. `build_join_auth()` in this project produces exactly
  that mapping; it can be passed to the SDK if you prefer its client.
- The SDK and CLI confirm the event names, message frame, and reconnect
  behavior. The authorization details come from the web bundle.

## Live verification

The opt-in live test in `tests/test_live.py` joins a random private room with
two clients and exchanges a message. Run it with:

```sh
ORZCHAT_LIVE_TEST=1 pytest tests/test_live.py -v
```

It talks to the real service. Use a random room name and avoid running it in a
loop; the public queue is for people, not automated clients.
