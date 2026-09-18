import json
from unittest import mock

import pytest

from extract_memes.telegram_uploader import ALBUM_LIMIT, TelegramUploader


def response(ok=True, result=None, description=None):
    resp = mock.Mock()
    resp.json.return_value = {"ok": ok, "result": result, "description": description}
    resp.text = json.dumps({"ok": ok, "description": description})
    return resp


def default_post(url, **kwargs):
    if url.endswith("/sendMessage"):
        return response(result={"message_id": 111})
    if url.endswith("/sendMediaGroup"):
        return response(result=[{}])
    raise AssertionError(f"unexpected call to {url}")


@pytest.fixture
def post():
    with mock.patch("extract_memes.telegram_uploader.requests.post") as post:
        post.side_effect = default_post
        yield post


def images(tmp_path, count):
    paths = []
    for i in range(count):
        path = tmp_path / f"meme_{i:03d}.png"
        path.write_bytes(b"not really an image")
        paths.append(path)
    return paths


def calls_to(post, method):
    return [call for call in post.call_args_list if call.args[0].endswith(f"/{method}")]


def test_missing_credentials_raise_before_any_request(post):
    with pytest.raises(ValueError, match="Telegram bot token"):
        TelegramUploader()

    post.assert_not_called()


def test_env_var_fallback(monkeypatch, post, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "env-chat")

    TelegramUploader().upload_all(images(tmp_path, 1), "https://youtu.be/xyz")

    assert calls_to(post, "sendMessage")[0].args[0] == "https://api.telegram.org/botenv-tok/sendMessage"


def test_empty_image_list_makes_no_requests(post):
    TelegramUploader(bot_token="tok", chat_id="123").upload_all([], "https://youtu.be/xyz")

    post.assert_not_called()


def test_posts_the_source_as_a_message_then_one_album(post, tmp_path):
    paths = images(tmp_path, 3)

    TelegramUploader(bot_token="tok", chat_id="123").upload_all(paths, "https://youtu.be/xyz")

    [link_call] = calls_to(post, "sendMessage")
    assert link_call.args[0] == "https://api.telegram.org/bottok/sendMessage"
    assert link_call.kwargs["data"] == {"chat_id": "123", "text": "https://youtu.be/xyz"}

    [album_call] = calls_to(post, "sendMediaGroup")
    assert album_call.kwargs["data"]["chat_id"] == "123"
    assert album_call.kwargs["data"]["reply_to_message_id"] == 111
    media = json.loads(album_call.kwargs["data"]["media"])
    assert [item["media"] for item in media] == ["attach://photo0", "attach://photo1", "attach://photo2"]
    assert list(album_call.kwargs["files"].keys()) == ["photo0", "photo1", "photo2"]
    assert [name for name, _ in album_call.kwargs["files"].values()] == [p.name for p in paths]


def test_chunks_more_than_the_album_limit_into_several_albums(post, tmp_path):
    paths = images(tmp_path, ALBUM_LIMIT + 5)

    TelegramUploader(bot_token="tok", chat_id="123").upload_all(paths, "https://youtu.be/xyz")

    albums = calls_to(post, "sendMediaGroup")
    assert len(albums) == 2
    sizes = [len(json.loads(call.kwargs["data"]["media"])) for call in albums]
    assert sizes == [ALBUM_LIMIT, 5]
    assert all(call.kwargs["data"]["reply_to_message_id"] == 111 for call in albums)


def test_link_message_failure_still_sends_albums_without_a_reply(post, tmp_path, capsys):
    def failing_link(url, **kwargs):
        if url.endswith("/sendMessage"):
            return response(ok=False, description="Forbidden: bot was blocked")
        return default_post(url, **kwargs)

    post.side_effect = failing_link
    paths = images(tmp_path, 2)

    TelegramUploader(bot_token="tok", chat_id="123").upload_all(paths, "https://youtu.be/xyz")

    [album_call] = calls_to(post, "sendMediaGroup")
    assert "reply_to_message_id" not in album_call.kwargs["data"]
    assert "Failed to post the source link" in capsys.readouterr().out


def test_a_failed_album_is_logged_and_other_albums_still_sent(post, tmp_path, capsys):
    calls = {"n": 0}

    def one_album_fails(url, **kwargs):
        if url.endswith("/sendMediaGroup"):
            calls["n"] += 1
            if calls["n"] == 1:
                return response(ok=False, description="Bad Request: file too large")
        return default_post(url, **kwargs)

    post.side_effect = one_album_fails
    paths = images(tmp_path, ALBUM_LIMIT + 3)

    TelegramUploader(bot_token="tok", chat_id="123").upload_all(paths, "https://youtu.be/xyz")

    assert len(calls_to(post, "sendMediaGroup")) == 2
    out = capsys.readouterr().out
    assert "Upload failed for" in out
    assert f"{ALBUM_LIMIT} of {len(paths)} uploads failed." in out


def test_image_files_are_closed_after_each_album(post, tmp_path):
    paths = images(tmp_path, 2)
    opened = []
    real_open = open

    def tracking_open(path, *args, **kwargs):
        file = real_open(path, *args, **kwargs)
        if str(path) in [str(p) for p in paths]:
            opened.append(file)
        return file

    with mock.patch("extract_memes.telegram_uploader.open", tracking_open):
        TelegramUploader(bot_token="tok", chat_id="123").upload_all(paths, "https://youtu.be/xyz")

    assert len(opened) == 2
    assert all(file.closed for file in opened)
