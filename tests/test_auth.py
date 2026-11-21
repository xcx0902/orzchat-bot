import hashlib

import pytest

from orzchat_bot.auth import (
    DEFAULT_AUTH_SALT,
    build_join_auth,
    make_nonce,
    sign_join,
)


def test_default_salt_matches_the_published_web_bundle():
    assert DEFAULT_AUTH_SALT == "orz_front_salt_3e8b1d9c2a7f5e0a6d4b8c9e1f2a3b4c"


def test_signature_matches_the_web_client_algorithm():
    timestamp_ms = 1795230905196
    nonce = "ocffmocenak7gfqv"
    room_id = "my-room"
    expected = hashlib.sha256(
        f"{timestamp_ms}:{nonce}:{room_id}:{DEFAULT_AUTH_SALT}".encode()
    ).hexdigest()
    assert sign_join(room_id, timestamp_ms, nonce, DEFAULT_AUTH_SALT) == expected


def test_known_signature_from_the_web_client():
    # Captured from a browser-style join that the live server accepted.
    assert (
        sign_join("", 1795230905196, "ocffmocenak7gfqv", DEFAULT_AUTH_SALT)
        == "fd10b401699752c78175802fe60fecd1203da9cc6a8967ad52f1e04f2a20882f"
    )


def test_build_join_auth_is_deterministic_when_inputs_are_fixed():
    auth = build_join_auth(
        "R",
        timestamp_ms=1700000000000,
        nonce="abcdefghijklmnop",
    )
    assert auth == {
        "ts": 1700000000000,
        "nonce": "abcdefghijklmnop",
        "sig": hashlib.sha256(
            f"1700000000000:abcdefghijklmnop:R:{DEFAULT_AUTH_SALT}".encode()
        ).hexdigest(),
    }


def test_make_nonce_uses_lowercase_alphanumerics():
    nonce = make_nonce()
    assert len(nonce) == 16
    assert nonce.isascii()
    assert nonce.isalnum()
    assert nonce == nonce.lower()


def test_empty_salt_is_rejected():
    with pytest.raises(ValueError):
        sign_join("", 1, "x", "")
