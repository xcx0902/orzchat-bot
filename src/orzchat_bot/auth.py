"""OrzChat join authorization.

The hosted OrzChat server expects a short-lived, stateless authorization
object in the ``join`` frame::

    {"type": "join", "room_id": "room", "auth": {"ts": ..., "nonce": ..., "sig": ...}}

The signature is::

    sig = sha256(f"{ts}:{nonce}:{room_id}:{salt}").hexdigest()

Both the exact signing string and the salt come from OrzChat's public web
bundle.  The salt below is the value currently embedded there (obfuscated with
a XOR).  If OrzChat rotates the salt, the server answers with
``{"type": "error", "message": "Unauthorized"}``; set ``ORZCHAT_AUTH_SALT`` or
pass ``--auth-salt`` to use the new value.
"""

from __future__ import annotations

import hashlib
import secrets
import string
import time
from typing import TypedDict

# The web client stores the salt as bytes XORed with 90:
#   [53, 40, 32, ...].map(b => String.fromCharCode(90 ^ b)).join("")
# Keep the encoded form so it is easy to compare with the published bundle.
_SITE_SALT_BYTES: tuple[int, ...] = (
    53,
    40,
    32,
    5,
    60,
    40,
    53,
    52,
    46,
    5,
    41,
    59,
    54,
    46,
    5,
    105,
    63,
    98,
    56,
    107,
    62,
    99,
    57,
    104,
    59,
    109,
    60,
    111,
    63,
    106,
    59,
    108,
    62,
    110,
    56,
    98,
    57,
    99,
    63,
    107,
    60,
    104,
    59,
    105,
    56,
    110,
    57,
)

DEFAULT_AUTH_SALT = "".join(chr(90 ^ byte) for byte in _SITE_SALT_BYTES)

NONCE_LENGTH = 16
_NONCE_ALPHABET = string.ascii_lowercase + string.digits


class JoinAuth(TypedDict):
    """The JSON object sent as the ``auth`` field of a ``join`` frame."""

    ts: int
    nonce: str
    sig: str


def make_nonce(length: int = NONCE_LENGTH) -> str:
    """Return a random nonce in the same alphabet as the web client's."""
    if length < 1:
        raise ValueError("Nonce length must be positive.")
    return "".join(secrets.choice(_NONCE_ALPHABET) for _ in range(length))


def sign_join(room_id: str, timestamp_ms: int, nonce: str, salt: str) -> str:
    """Return the hex SHA-256 signature for a join authorization."""
    if not salt:
        raise ValueError("The join authorization salt must not be empty.")
    message = f"{timestamp_ms}:{nonce}:{room_id}:{salt}"
    return hashlib.sha256(message.encode("utf-8")).hexdigest()


def build_join_auth(
    room_id: str = "",
    *,
    salt: str = DEFAULT_AUTH_SALT,
    timestamp_ms: int | None = None,
    nonce: str | None = None,
) -> JoinAuth:
    """Build a fresh authorization object for a room.

    ``timestamp_ms`` and ``nonce`` are injectable for tests.  Production calls
    use the current wall clock and a cryptographically random nonce.
    """
    if not isinstance(room_id, str):
        raise TypeError("room_id must be a string.")
    ts = int(time.time() * 1000) if timestamp_ms is None else int(timestamp_ms)
    actual_nonce = make_nonce() if nonce is None else nonce
    if not actual_nonce:
        raise ValueError("nonce must not be empty.")
    return {
        "ts": ts,
        "nonce": actual_nonce,
        "sig": sign_join(room_id, ts, actual_nonce, salt),
    }
