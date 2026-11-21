import pytest

from orzchat_bot.text import fit_message, normalize_text, preview


def test_normalize_handles_line_endings_and_control_characters():
    assert normalize_text("  a\r\nb\x00c\t \r\n\r\n\r\nd  ") == "a\nbc\n\nd"


def test_normalize_collapses_excess_blank_lines():
    assert normalize_text("one\n\n\n\n\ntwo") == "one\n\ntwo"


def test_short_message_is_unchanged():
    assert fit_message("hello there", 300) == "hello there"


def test_long_message_is_cut_at_a_word_boundary():
    text = "word " * 100
    result = fit_message(text, 300)
    assert len(result) <= 300
    assert result.endswith("\u2026")
    assert not result[:-1].endswith(" wor")
    assert result.startswith("word word")


def test_long_message_prefers_a_sentence_boundary():
    result = fit_message(("A short sentence. " * 30).strip(), 100)
    assert len(result) <= 100
    assert result.endswith("sentence.\u2026")


def test_cjk_without_spaces_is_hard_cut():
    result = fit_message("哈" * 500, 300)
    assert len(result) == 300
    assert result.endswith("\u2026")


def test_fit_message_rejects_zero_limit():
    with pytest.raises(ValueError):
        fit_message("x", 0)


def test_preview_truncates_and_quotes():
    assert preview("hello", 10) == "'hello'"
    assert preview("a" * 20, 10) == "'aaaaaaaaa\u2026'"
