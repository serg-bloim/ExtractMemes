import json
from unittest import mock

import pytest

from extract_memes.downloader import SourceInfo
from extract_memes.telegram_uploader import ALBUM_LIMIT, CAPTION_LIMIT, TelegramUploader


def response(ok=True, result=None, description=None):
    resp = mock.Mock()
    resp.json.return_value = {"ok": ok, "result": result, "description": description}
    resp.text = json.dumps({"ok": ok, "description": description})
    return resp


def default_post(url, **kwargs):
    if url.endswith(("/sendMessage", "/sendPhoto")):
        return response(result={"message_id": 111})
    if url.endswith("/sendMediaGroup"):
        return response(result=[{}])
    if url.endswith("/getChat"):
        return response(result={"id": -100, "type": "channel"})
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


INFO = SourceInfo(title="Best memes", thumbnail_url="https://img.example/t.jpg")


def test_parent_post_is_the_thumbnail_with_title_and_link_as_caption(post, tmp_path):
    TelegramUploader(bot_token="tok", chat_id="123").upload_all(images(tmp_path, 2), "https://youtu.be/xyz", INFO)

    [photo_call] = calls_to(post, "sendPhoto")
    assert photo_call.kwargs["data"] == {
        "chat_id": "123",
        "photo": "https://img.example/t.jpg",
        "caption": "Best memes\nhttps://youtu.be/xyz",
    }
    assert calls_to(post, "sendMessage") == []
    [album_call] = calls_to(post, "sendMediaGroup")
    assert album_call.kwargs["data"]["reply_to_message_id"] == 111


def test_a_long_title_is_cut_to_fit_the_caption_limit(post, tmp_path):
    info = SourceInfo(title="x" * 2000, thumbnail_url="https://img.example/t.jpg")

    TelegramUploader(bot_token="tok", chat_id="123").upload_all(images(tmp_path, 1), "https://youtu.be/xyz", info)

    [photo_call] = calls_to(post, "sendPhoto")
    caption = photo_call.kwargs["data"]["caption"]
    assert len(caption) == CAPTION_LIMIT
    assert caption.endswith("\nhttps://youtu.be/xyz")


def test_failed_thumbnail_falls_back_to_a_title_and_link_message(post, tmp_path):
    def photo_fails(url, **kwargs):
        if url.endswith("/sendPhoto"):
            return response(ok=False, description="Bad Request: wrong file identifier/HTTP URL")
        return default_post(url, **kwargs)

    post.side_effect = photo_fails

    TelegramUploader(bot_token="tok", chat_id="123").upload_all(images(tmp_path, 1), "https://youtu.be/xyz", INFO)

    [message_call] = calls_to(post, "sendMessage")
    assert message_call.kwargs["data"]["text"] == "Best memes\nhttps://youtu.be/xyz"
    assert calls_to(post, "sendMediaGroup")[0].kwargs["data"]["reply_to_message_id"] == 111


def test_info_without_a_thumbnail_posts_title_and_link_as_text(post, tmp_path):
    info = SourceInfo(title="Best memes")

    TelegramUploader(bot_token="tok", chat_id="123").upload_all(images(tmp_path, 1), "https://youtu.be/xyz", info)

    assert calls_to(post, "sendPhoto") == []
    [message_call] = calls_to(post, "sendMessage")
    assert message_call.kwargs["data"]["text"] == "Best memes\nhttps://youtu.be/xyz"


def test_everything_failing_falls_back_to_the_bare_link_then_no_reply(post, tmp_path, capsys):
    def only_bare_link_works(url, **kwargs):
        if url.endswith("/sendMessage") and kwargs["data"]["text"] == "https://youtu.be/xyz":
            return response(result={"message_id": 222})
        if url.endswith(("/sendPhoto", "/sendMessage")):
            return response(ok=False, description="nope")
        return default_post(url, **kwargs)

    post.side_effect = only_bare_link_works

    TelegramUploader(bot_token="tok", chat_id="123").upload_all(images(tmp_path, 1), "https://youtu.be/xyz", INFO)

    assert calls_to(post, "sendMediaGroup")[0].kwargs["data"]["reply_to_message_id"] == 222


CHANNEL = -1001
DISCUSSION = -1002


def forward_update(update_id=7, post_id=111, forwarded_id=555, discussion=DISCUSSION, channel=CHANNEL):
    return {
        "update_id": update_id,
        "message": {
            "message_id": forwarded_id,
            "chat": {"id": discussion},
            "is_automatic_forward": True,
            "forward_origin": {"type": "channel", "chat": {"id": channel}, "message_id": post_id},
        },
    }


def comments_post(updates_by_call):
    """A `post` side effect for a channel with a linked discussion group.

    `updates_by_call` is a list of `getUpdates` results, one per call (the last repeats).
    """
    calls = {"n": 0}

    def side_effect(url, **kwargs):
        if url.endswith("/getChat"):
            return response(result={"id": CHANNEL, "type": "channel", "linked_chat_id": DISCUSSION})
        if url.endswith("/getUpdates"):
            result = updates_by_call[min(calls["n"], len(updates_by_call) - 1)]
            calls["n"] += 1
            return response(result=result)
        return default_post(url, **kwargs)

    return side_effect


def test_albums_go_to_the_discussion_group_as_comments_on_the_forwarded_post(post, tmp_path):
    post.side_effect = comments_post([[forward_update()]])

    TelegramUploader(bot_token="tok", chat_id="@chan").upload_all(images(tmp_path, ALBUM_LIMIT + 2), "https://youtu.be/xyz")

    albums = calls_to(post, "sendMediaGroup")
    assert len(albums) == 2
    for call in albums:
        assert call.kwargs["data"]["chat_id"] == DISCUSSION
        assert call.kwargs["data"]["reply_to_message_id"] == 555


def test_unrelated_and_stale_forwards_are_skipped_while_waiting(post, tmp_path):
    stale = forward_update(update_id=1, post_id=99, forwarded_id=444)
    other_group = forward_update(update_id=2, discussion=-1999)
    post.side_effect = comments_post([[stale, other_group], [forward_update(update_id=3)]])

    TelegramUploader(bot_token="tok", chat_id="@chan").upload_all(images(tmp_path, 1), "https://youtu.be/xyz")

    [album] = calls_to(post, "sendMediaGroup")
    assert album.kwargs["data"]["reply_to_message_id"] == 555
    offsets = [c.kwargs["data"].get("offset") for c in calls_to(post, "getUpdates")]
    assert offsets == [None, 3]


def test_missing_forward_falls_back_to_replying_in_the_chat(post, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("extract_memes.telegram_uploader.DISCUSSION_WAIT_SECONDS", 0)
    post.side_effect = comments_post([[]])

    TelegramUploader(bot_token="tok", chat_id="123").upload_all(images(tmp_path, 1), "https://youtu.be/xyz")

    [album] = calls_to(post, "sendMediaGroup")
    assert album.kwargs["data"]["chat_id"] == "123"
    assert album.kwargs["data"]["reply_to_message_id"] == 111
    assert "comments thread never appeared" in capsys.readouterr().out


def test_chat_without_a_discussion_group_never_polls(post, tmp_path):
    TelegramUploader(bot_token="tok", chat_id="123").upload_all(images(tmp_path, 1), "https://youtu.be/xyz")

    assert calls_to(post, "getUpdates") == []
    assert calls_to(post, "sendMediaGroup")[0].kwargs["data"]["reply_to_message_id"] == 111


def test_no_comments_lookup_when_the_parent_post_failed(post, tmp_path):
    def parent_fails(url, **kwargs):
        if url.endswith("/sendMessage"):
            return response(ok=False, description="nope")
        return default_post(url, **kwargs)

    post.side_effect = parent_fails

    TelegramUploader(bot_token="tok", chat_id="123").upload_all(images(tmp_path, 1), "https://youtu.be/xyz")

    assert calls_to(post, "getChat") == []
