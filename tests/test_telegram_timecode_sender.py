import json
from unittest import mock

import pytest

from extract_memes.telegram_timecode_sender import TelegramTimecodeSender


def response(ok=True, result=None, description=None):
    resp = mock.Mock()
    resp.json.return_value = {"ok": ok, "result": result, "description": description}
    resp.text = json.dumps({"ok": ok, "description": description})
    return resp


def default_post(url, **kwargs):
    if url.endswith("/sendMessage"):
        return response(result={"message_id": 111})
    raise AssertionError(f"unexpected call to {url}")


@pytest.fixture
def post():
    with mock.patch("extract_memes.telegram_timecode_sender.requests.post") as post:
        post.side_effect = default_post
        yield post


def calls_to(post, method):
    return [call for call in post.call_args_list if call.args[0].endswith(f"/{method}")]


def test_missing_credentials_raise_before_any_request(post):
    with pytest.raises(ValueError, match="Telegram bot token"):
        TelegramTimecodeSender()

    post.assert_not_called()


def test_env_var_fallback(monkeypatch, post):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-tok")
    monkeypatch.setenv("TELEGRAM_TIMECODES_CHAT_ID", "env-chat")

    TelegramTimecodeSender().send(["0:07 Мем 1"], "https://youtu.be/xyz")

    [link_call, _reply_call] = calls_to(post, "sendMessage")
    assert link_call.args[0] == "https://api.telegram.org/botenv-tok/sendMessage"
    assert link_call.kwargs["data"]["chat_id"] == "env-chat"


def test_bot_token_arg_with_env_chat_id(monkeypatch, post):
    monkeypatch.setenv("TELEGRAM_TIMECODES_CHAT_ID", "env-chat")

    TelegramTimecodeSender(bot_token="tok").send(["0:07 Мем 1"], "https://youtu.be/xyz")

    [link_call, _reply_call] = calls_to(post, "sendMessage")
    assert link_call.args[0] == "https://api.telegram.org/bottok/sendMessage"
    assert link_call.kwargs["data"]["chat_id"] == "env-chat"


def test_empty_timecode_list_makes_no_requests(post):
    TelegramTimecodeSender(bot_token="tok", chat_id="123").send([], "https://youtu.be/xyz")

    post.assert_not_called()


def test_posts_the_source_then_a_reply_with_the_timecodes(post):
    timecodes = ["0:07 Мем 1", "0:28 Мем 2"]

    TelegramTimecodeSender(bot_token="tok", chat_id="123").send(timecodes, "https://youtu.be/xyz")

    [link_call, reply_call] = calls_to(post, "sendMessage")
    assert link_call.kwargs["data"] == {"chat_id": "123", "text": "https://youtu.be/xyz"}
    assert reply_call.kwargs["data"] == {
        "chat_id": "123",
        "text": "0:07 Мем 1\n0:28 Мем 2",
        "reply_to_message_id": 111,
    }


def test_link_message_failure_still_sends_the_reply_without_a_reply_to(post, capsys):
    def failing_link(url, **kwargs):
        if url.endswith("/sendMessage") and post.call_count == 1:
            return response(ok=False, description="Forbidden: bot was blocked")
        return default_post(url, **kwargs)

    post.side_effect = failing_link

    TelegramTimecodeSender(bot_token="tok", chat_id="123").send(["0:07 Мем 1"], "https://youtu.be/xyz")

    [_failed_link, reply_call] = calls_to(post, "sendMessage")
    assert "reply_to_message_id" not in reply_call.kwargs["data"]
    assert "Failed to post the source link" in capsys.readouterr().out


def test_a_failed_reply_is_logged_and_does_not_raise(post, capsys):
    def failing_reply(url, **kwargs):
        if url.endswith("/sendMessage") and post.call_count == 2:
            return response(ok=False, description="Bad Request: message too long")
        return default_post(url, **kwargs)

    post.side_effect = failing_reply

    TelegramTimecodeSender(bot_token="tok", chat_id="123").send(["0:07 Мем 1"], "https://youtu.be/xyz")

    assert "Failed to post timecodes" in capsys.readouterr().out
