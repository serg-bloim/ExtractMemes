import importlib
from unittest import mock

import pytest

from extract_memes import playlist_watch
from extract_memes.playlist_watch import (
    append_processed,
    find_next_unprocessed,
    list_playlist_video_ids,
    read_processed,
)

PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLfake"


@pytest.fixture
def fake_ytdl():
    with mock.patch("yt_dlp.YoutubeDL") as youtube_dl:
        ydl = youtube_dl.return_value.__enter__.return_value
        ydl.extract_info.return_value = {
            "entries": [{"id": "newest"}, {"id": "middle"}, {"id": "oldest"}]
        }
        yield youtube_dl


def test_list_playlist_video_ids_uses_flat_extraction(fake_ytdl):
    result = list_playlist_video_ids(PLAYLIST_URL, count=3)

    options = fake_ytdl.call_args.args[0]
    assert options["extract_flat"] == "in_playlist"
    assert options["playlistend"] == 3
    ydl = fake_ytdl.return_value.__enter__.return_value
    ydl.extract_info.assert_called_once_with(PLAYLIST_URL, download=False)
    assert result == ["newest", "middle", "oldest"]


def test_importing_module_does_not_touch_yt_dlp():
    with mock.patch("yt_dlp.YoutubeDL") as youtube_dl:
        importlib.reload(playlist_watch)
    youtube_dl.assert_not_called()


def test_read_processed_missing_file_returns_empty_set(tmp_path):
    assert read_processed(tmp_path / "processed.txt") == set()


def test_read_processed_ignores_blank_lines(tmp_path):
    path = tmp_path / "processed.txt"
    path.write_text("abc\n\ndef\n")

    assert read_processed(path) == {"abc", "def"}


def test_append_processed_creates_file_and_parents(tmp_path):
    path = tmp_path / "nested" / "processed.txt"

    append_processed(path, "abc")
    append_processed(path, "def")

    assert path.read_text() == "abc\ndef\n"


def test_find_next_unprocessed_returns_oldest_not_processed():
    video_ids = ["newest", "middle", "oldest"]

    assert find_next_unprocessed(video_ids, processed=set()) == "oldest"
    assert find_next_unprocessed(video_ids, processed={"oldest"}) == "middle"
    assert find_next_unprocessed(video_ids, processed={"oldest", "middle"}) == "newest"


def test_find_next_unprocessed_returns_none_when_all_processed():
    video_ids = ["newest", "middle", "oldest"]

    assert find_next_unprocessed(video_ids, processed=set(video_ids)) is None


def test_cli_find_prints_next_unprocessed_id(tmp_path, capsys, fake_ytdl):
    processed_file = tmp_path / "processed.txt"
    processed_file.write_text("oldest\n")

    playlist_watch.main(
        [
            "find",
            "--playlist-url",
            PLAYLIST_URL,
            "--processed-file",
            str(processed_file),
        ]
    )

    assert capsys.readouterr().out == "middle\n"


def test_cli_find_prints_nothing_when_all_processed(tmp_path, capsys, fake_ytdl):
    processed_file = tmp_path / "processed.txt"
    processed_file.write_text("newest\nmiddle\noldest\n")

    playlist_watch.main(
        [
            "find",
            "--playlist-url",
            PLAYLIST_URL,
            "--processed-file",
            str(processed_file),
        ]
    )

    assert capsys.readouterr().out == ""


def test_cli_mark_processed_appends_id(tmp_path):
    processed_file = tmp_path / "processed.txt"

    playlist_watch.main(["mark-processed", "abc123", "--processed-file", str(processed_file)])

    assert processed_file.read_text() == "abc123\n"
