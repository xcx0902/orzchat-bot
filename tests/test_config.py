import pytest

from orzchat_bot.config import ConfigurationError, Settings, normalize_room_id


def test_normalize_room_id_strips_slashes_and_whitespace():
    assert normalize_room_id("  /my-room  ") == "my-room"
    assert normalize_room_id("") == ""


def test_long_room_names_are_rejected():
    with pytest.raises(ConfigurationError):
        normalize_room_id("x" * 51)


def test_from_env_reads_the_documented_variables(monkeypatch):
    monkeypatch.setenv("ORZCHAT_ROOM", "/env-room")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "local")
    monkeypatch.setenv("OPENAI_MODEL", "tiny")
    monkeypatch.setenv("OPENAI_TEMPERATURE", "none")
    monkeypatch.setenv("BOT_MAX_HISTORY", "3")
    monkeypatch.setenv("BOT_DRY_RUN", "true")
    settings = Settings.from_env()
    assert settings.room_id == "env-room"
    assert settings.base_url == "http://localhost:1234/v1"
    assert settings.api_key == "local"
    assert settings.model == "tiny"
    assert settings.temperature is None
    assert settings.max_history == 3
    assert settings.dry_run is True
    settings.validate()


def test_proxy_none_disables_proxy_settings(monkeypatch):
    monkeypatch.setenv("ORZCHAT_PROXY", "none")
    monkeypatch.setenv("OPENAI_PROXY", "direct")
    settings = Settings.from_env()
    assert settings.proxy is None
    assert settings.api_proxy is None


def test_hello_message_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("BOT_HELLO_MESSAGE", "  Hi there!  ")
    assert Settings.from_env().hello_message == "Hi there!"
    monkeypatch.setenv("BOT_HELLO_MESSAGE", "   ")
    assert Settings.from_env().hello_message is None


def test_invalid_boolean_is_rejected(monkeypatch):
    monkeypatch.setenv("BOT_ONCE", "sometimes")
    with pytest.raises(ConfigurationError):
        Settings.from_env()


def test_model_and_key_are_required_for_real_runs():
    with pytest.raises(ConfigurationError):
        Settings().validate()


def test_dry_run_does_not_require_a_model():
    Settings(dry_run=True).validate()


def test_reply_limit_cannot_exceed_the_site_limit():
    with pytest.raises(ConfigurationError):
        Settings(model="m", api_key="k", max_reply_chars=301).validate()


def test_temperature_range_is_validated():
    with pytest.raises(ConfigurationError):
        Settings(model="m", api_key="k", temperature=3.0).validate()
