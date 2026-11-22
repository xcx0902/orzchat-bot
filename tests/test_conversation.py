import pytest

from orzchat_bot.conversation import Conversation


def test_build_messages_starts_with_system_and_current_user():
    conversation = Conversation("be nice", max_exchanges=10)
    assert conversation.build_messages("hello") == [
        {"role": "system", "content": "be nice"},
        {"role": "user", "content": "hello"},
    ]


def test_completed_exchanges_are_included_in_order():
    conversation = Conversation("be nice", max_exchanges=10)
    conversation.record_exchange("one", "first")
    conversation.record_exchange("two", "second")
    assert conversation.build_messages("three") == [
        {"role": "system", "content": "be nice"},
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "first"},
        {"role": "user", "content": "two"},
        {"role": "assistant", "content": "second"},
        {"role": "user", "content": "three"},
    ]


def test_greeting_is_included_before_the_first_user_turn():
    conversation = Conversation("be nice", max_exchanges=5)
    conversation.set_opening("Hello!")
    conversation.record_exchange("one", "first")
    assert conversation.build_messages("two") == [
        {"role": "system", "content": "be nice"},
        {"role": "assistant", "content": "Hello!"},
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "first"},
        {"role": "user", "content": "two"},
    ]


def test_reset_clears_the_greeting():
    conversation = Conversation("s", max_exchanges=5)
    conversation.set_opening("Hello!")
    conversation.reset()
    assert conversation.build_messages("hi") == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "hi"},
    ]


def test_oldest_exchanges_are_dropped_as_a_pair():
    conversation = Conversation("s", max_exchanges=2)
    for index in range(4):
        conversation.record_exchange(f"u{index}", f"a{index}")
    messages = conversation.build_messages("now")
    assert conversation.exchange_count == 2
    assert [message["content"] for message in messages] == [
        "s",
        "u2",
        "a2",
        "u3",
        "a3",
        "now",
    ]


def test_zero_history_still_sends_the_current_message():
    conversation = Conversation("s", max_exchanges=0)
    conversation.record_exchange("old", "reply")
    assert conversation.build_messages("new") == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "new"},
    ]


def test_reset_clears_history():
    conversation = Conversation("s", max_exchanges=5)
    conversation.record_exchange("one", "two")
    conversation.reset()
    assert conversation.build_messages("three") == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "three"},
    ]


def test_negative_history_is_rejected():
    with pytest.raises(ValueError):
        Conversation("s", max_exchanges=-1)
