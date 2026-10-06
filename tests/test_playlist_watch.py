import datetime
import importlib
from unittest import mock

import pytest

from extract_memes import playlist_watch
from extract_memes.playlist_watch import (
    append_processed,
    find_next_unprocessed,
    list_playlist_video_ids,
    load_upload_dates,
    read_processed,
    save_upload_dates,
)

PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLfake"
SINCE = datetime.date(2026, 10, 1)


@pytest.fixture
def fake_ytdl():
    with mock.patch("yt_dlp.YoutubeDL") as youtube_dl:
        ydl = youtube_dl.return_value.__enter__.return_value
        ydl.extract_info.return_value = {
            "entries": [
                {"id": "newest", "upload_date": "20261004"},
                {"id": "middle", "upload_date": "20261002"},
                {"id": "oldest", "upload_date": "20261001"},
                {"id": "too-old", "upload_date": "20260930"},
            ]
        }
        yield youtube_dl


def test_list_playlist_video_ids_uses_flat_extraction(fake_ytdl):
    result = list_playlist_video_ids(PLAYLIST_URL, SINCE)

    options = fake_ytdl.call_args.args[0]
    assert options["extract_flat"] == "in_playlist"
    ydl = fake_ytdl.return_value.__enter__.return_value
    ydl.extract_info.assert_called_once_with(PLAYLIST_URL, download=False)
    assert result == ["newest", "middle", "oldest"]


def test_list_playlist_video_ids_fetches_date_when_flat_entry_lacks_it(fake_ytdl):
    ydl = fake_ytdl.return_value.__enter__.return_value
    ydl.extract_info.side_effect = [
        {"entries": [{"id": "a"}, {"id": "b"}]},
        {"upload_date": "20261003"},
        {"upload_date": "20260901"},
    ]

    assert list_playlist_video_ids(PLAYLIST_URL, SINCE) == ["a"]


def test_list_playlist_video_ids_passes_proxy_when_given(fake_ytdl):
    list_playlist_video_ids(PLAYLIST_URL, SINCE, proxy="socks5h://127.0.0.1:1080")

    options = fake_ytdl.call_args.args[0]
    assert options["proxy"] == "socks5h://127.0.0.1:1080"


def test_list_playlist_video_ids_omits_proxy_when_unset(fake_ytdl):
    list_playlist_video_ids(PLAYLIST_URL, SINCE)

    options = fake_ytdl.call_args.args[0]
    assert "proxy" not in options


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
            "--since",
            "2026-10-01",
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
            "--since",
            "2026-10-01",
            "--processed-file",
            str(processed_file),
        ]
    )

    assert capsys.readouterr().out == ""


def test_cli_find_proxy_flag_reaches_list_playlist_video_ids(tmp_path, monkeypatch, fake_ytdl):
    monkeypatch.delenv("EXTRACT_MEMES_PROXY", raising=False)
    processed_file = tmp_path / "processed.txt"

    playlist_watch.main(
        [
            "find",
            "--playlist-url",
            PLAYLIST_URL,
            "--processed-file",
            str(processed_file),
            "--proxy",
            "socks5h://127.0.0.1:1080",
        ]
    )

    options = fake_ytdl.call_args.args[0]
    assert options["proxy"] == "socks5h://127.0.0.1:1080"


def test_cli_find_proxy_falls_back_to_env_var(tmp_path, monkeypatch, fake_ytdl):
    monkeypatch.setenv("EXTRACT_MEMES_PROXY", "socks5h://127.0.0.1:1080")
    processed_file = tmp_path / "processed.txt"

    playlist_watch.main(
        ["find", "--playlist-url", PLAYLIST_URL, "--processed-file", str(processed_file)]
    )

    options = fake_ytdl.call_args.args[0]
    assert options["proxy"] == "socks5h://127.0.0.1:1080"


def test_cli_mark_processed_appends_id(tmp_path):
    processed_file = tmp_path / "processed.txt"

    playlist_watch.main(["mark-processed", "abc123", "--processed-file", str(processed_file)])

    assert processed_file.read_text() == "abc123\n"


def flatless_ytdl(fake_ytdl, dates: dict[str, str]):
    """Make the playlist hold date-less entries `a`, `b`, … and answer each metadata fetch from `dates`."""
    ydl = fake_ytdl.return_value.__enter__.return_value

    def extract_info(url, download=False):
        if url == PLAYLIST_URL:
            return {"entries": [{"id": video_id} for video_id in dates]}
        return {"upload_date": dates[url]}

    ydl.extract_info.side_effect = extract_info
    return ydl


def test_a_cached_date_is_not_fetched(fake_ytdl):
    ydl = flatless_ytdl(fake_ytdl, {"a": "20261003", "b": "20260901"})

    result = list_playlist_video_ids(PLAYLIST_URL, SINCE, upload_dates={"a": "2026-10-03", "b": "2026-09-01"})

    assert result == ["a"]
    ydl.extract_info.assert_called_once_with(PLAYLIST_URL, download=False)


def test_a_fetched_date_is_added_to_the_cache_in_place(fake_ytdl):
    flatless_ytdl(fake_ytdl, {"a": "20261003", "b": "20260901"})
    cache = {"a": "2026-10-03"}

    list_playlist_video_ids(PLAYLIST_URL, SINCE, upload_dates=cache)

    assert cache == {"a": "2026-10-03", "b": "2026-09-01"}


def test_a_video_without_a_date_is_kept_and_not_cached(fake_ytdl):
    ydl = fake_ytdl.return_value.__enter__.return_value
    ydl.extract_info.side_effect = [{"entries": [{"id": "a"}]}, {}]
    cache = {}

    assert list_playlist_video_ids(PLAYLIST_URL, SINCE, upload_dates=cache) == ["a"]
    assert cache == {}


def test_a_cached_date_is_never_overwritten(fake_ytdl):
    flatless_ytdl(fake_ytdl, {"a": "20250101"})
    cache = {"a": "2026-10-03"}

    list_playlist_video_ids(PLAYLIST_URL, SINCE, upload_dates=cache)

    assert cache == {"a": "2026-10-03"}


def test_dates_fetched_before_a_failure_stay_in_the_cache(fake_ytdl):
    ydl = fake_ytdl.return_value.__enter__.return_value
    ydl.extract_info.side_effect = [
        {"entries": [{"id": "a"}, {"id": "b"}]},
        {"upload_date": "20261003"},
        RuntimeError("network down"),
    ]
    cache = {}

    with pytest.raises(RuntimeError, match="network down"):
        list_playlist_video_ids(PLAYLIST_URL, SINCE, upload_dates=cache)

    assert cache == {"a": "2026-10-03"}


def test_load_upload_dates_missing_or_empty_file_is_empty(tmp_path):
    assert load_upload_dates(tmp_path / "missing.json") == {}
    empty = tmp_path / "empty.json"
    empty.write_text("  \n")
    assert load_upload_dates(empty) == {}


@pytest.mark.parametrize("text", ["{not json", "[1, 2]", '"text"'])
def test_load_upload_dates_invalid_file_is_empty_and_noted_on_stderr(tmp_path, capsys, text):
    path = tmp_path / "dates.json"
    path.write_text(text)

    assert load_upload_dates(path) == {}

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "upload-date cache" in captured.err


def test_save_upload_dates_round_trips_sorted_and_creates_parents(tmp_path):
    path = tmp_path / "nested" / "dates.json"

    save_upload_dates(path, {"b": "2026-10-02", "a": "2026-10-01"})

    assert path.read_text().index('"a"') < path.read_text().index('"b"')
    assert load_upload_dates(path) == {"a": "2026-10-01", "b": "2026-10-02"}


def test_cli_find_loads_and_saves_the_cache(tmp_path, capsys, fake_ytdl):
    ydl = flatless_ytdl(fake_ytdl, {"a": "20261003", "b": "20261002"})
    cache_file = tmp_path / "dates.json"
    save_upload_dates(cache_file, {"a": "2026-10-03"})

    playlist_watch.main(
        [
            "find",
            "--playlist-url",
            PLAYLIST_URL,
            "--since",
            "2026-10-01",
            "--processed-file",
            str(tmp_path / "processed.txt"),
            "--dates-cache",
            str(cache_file),
        ]
    )

    assert capsys.readouterr().out == "b\n"
    assert [call.args[0] for call in ydl.extract_info.call_args_list] == [PLAYLIST_URL, "b"]
    assert load_upload_dates(cache_file) == {"a": "2026-10-03", "b": "2026-10-02"}


def test_cli_find_saves_the_cache_even_when_the_fetch_fails(tmp_path, fake_ytdl):
    ydl = fake_ytdl.return_value.__enter__.return_value
    ydl.extract_info.side_effect = [
        {"entries": [{"id": "a"}, {"id": "b"}]},
        {"upload_date": "20261003"},
        RuntimeError("network down"),
    ]
    cache_file = tmp_path / "dates.json"

    with pytest.raises(RuntimeError, match="network down"):
        playlist_watch.main(
            [
                "find",
                "--playlist-url",
                PLAYLIST_URL,
                "--since",
                "2026-10-01",
                "--processed-file",
                str(tmp_path / "processed.txt"),
                "--dates-cache",
                str(cache_file),
            ]
        )

    assert load_upload_dates(cache_file) == {"a": "2026-10-03"}


def test_cli_find_does_not_write_the_cache_when_nothing_was_added(tmp_path, fake_ytdl):
    cache_file = tmp_path / "dates.json"

    playlist_watch.main(
        [
            "find",
            "--playlist-url",
            PLAYLIST_URL,
            "--since",
            "2026-10-01",
            "--processed-file",
            str(tmp_path / "processed.txt"),
            "--dates-cache",
            str(cache_file),
        ]
    )

    assert not cache_file.exists()
