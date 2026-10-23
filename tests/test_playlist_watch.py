import datetime
import importlib
from unittest import mock

import pytest

from extract_memes import playlist_watch
from extract_memes.playlist_watch import (
    find_next_unprocessed,
    list_playlist_video_ids,
    load_upload_dates,
    read_processed,
    save_upload_dates,
    set_status,
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


def test_list_playlist_video_ids_enables_the_node_js_runtime(fake_ytdl):
    list_playlist_video_ids(PLAYLIST_URL, SINCE)

    assert fake_ytdl.call_args.args[0]["js_runtimes"] == {"node": {}}


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


def test_read_processed_missing_file_returns_empty_dict(tmp_path):
    assert read_processed(tmp_path / "processed.txt") == {}


def test_read_processed_ignores_blank_lines_and_reads_statuses(tmp_path):
    path = tmp_path / "processed.txt"
    path.write_text("abc extracted\n\ndef uploaded\n")

    assert read_processed(path) == {"abc": "extracted", "def": "uploaded"}


def test_read_processed_treats_a_bare_id_as_uploaded(tmp_path):
    path = tmp_path / "processed.txt"
    path.write_text("old\nnew extracted\n")

    assert read_processed(path) == {"old": "uploaded", "new": "extracted"}


def test_set_status_creates_file_and_parents(tmp_path):
    path = tmp_path / "nested" / "processed.txt"

    set_status(path, "abc", "extracted")
    set_status(path, "def", "extracted")

    assert path.read_text() == "abc extracted\ndef extracted\n"


def test_set_status_replaces_a_line_in_place_and_converts_a_bare_id(tmp_path):
    path = tmp_path / "processed.txt"
    path.write_text("old\nabc extracted\ndef extracted\n")

    set_status(path, "abc", "uploaded")

    assert path.read_text() == "old uploaded\nabc uploaded\ndef extracted\n"
    assert not list(tmp_path.glob("*.tmp"))


def test_find_next_unprocessed_returns_oldest_not_processed():
    video_ids = ["newest", "middle", "oldest"]

    assert find_next_unprocessed(video_ids, processed={}) == "oldest"
    assert find_next_unprocessed(video_ids, processed={"oldest": "extracted"}) == "middle"
    assert find_next_unprocessed(video_ids, processed={"oldest": "uploaded", "middle": "extracted"}) == "newest"


def test_find_next_unprocessed_returns_none_when_all_processed():
    video_ids = ["newest", "middle", "oldest"]

    assert find_next_unprocessed(video_ids, processed=dict.fromkeys(video_ids, "extracted")) is None


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


def test_cli_set_status_records_ids_from_arguments_and_file(tmp_path):
    processed_file = tmp_path / "processed.txt"
    processed_file.write_text("a extracted\nb extracted\n")
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("b\nc\n")

    playlist_watch.main(
        ["set-status", "uploaded", "a", "--ids-file", str(ids_file), "--processed-file", str(processed_file)]
    )

    assert processed_file.read_text() == "a uploaded\nb uploaded\nc uploaded\n"


def test_cli_set_status_with_a_missing_ids_file_changes_nothing(tmp_path):
    processed_file = tmp_path / "processed.txt"

    playlist_watch.main(
        ["set-status", "uploaded", "--ids-file", str(tmp_path / "none.txt"), "--processed-file", str(processed_file)]
    )

    assert not processed_file.exists()


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


def test_on_new_date_is_called_after_each_fetched_date_only(fake_ytdl):
    flatless_ytdl(fake_ytdl, {"a": "20261003", "b": "20261002", "c": "20260901"})
    cache = {"a": "2026-10-03"}
    snapshots = []

    list_playlist_video_ids(
        PLAYLIST_URL, SINCE, upload_dates=cache, on_new_date=lambda: snapshots.append(dict(cache))
    )

    # `a` was cached, `b` and `c` were fetched; each call sees the date it was called for.
    assert snapshots == [
        {"a": "2026-10-03", "b": "2026-10-02"},
        {"a": "2026-10-03", "b": "2026-10-02", "c": "2026-09-01"},
    ]


def test_on_new_date_is_not_called_for_an_undetermined_date(fake_ytdl):
    ydl = fake_ytdl.return_value.__enter__.return_value
    ydl.extract_info.side_effect = [{"entries": [{"id": "a"}]}, {}]
    on_new_date = mock.Mock()

    list_playlist_video_ids(PLAYLIST_URL, SINCE, upload_dates={}, on_new_date=on_new_date)

    on_new_date.assert_not_called()


def test_cli_find_writes_the_cache_after_every_fetched_date(tmp_path, fake_ytdl):
    cache_file = tmp_path / "dates.json"
    on_disk = []

    def extract_info(url, download=False):
        if url == PLAYLIST_URL:
            return {"entries": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}
        on_disk.append(sorted(load_upload_dates(cache_file)))
        if url == "c":
            raise RuntimeError("killed")
        return {"upload_date": "20261003"}

    fake_ytdl.return_value.__enter__.return_value.extract_info.side_effect = extract_info

    with pytest.raises(RuntimeError, match="killed"):
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

    # The file already held each earlier date when the next video was fetched.
    assert on_disk == [[], ["a"], ["a", "b"]]


def test_save_upload_dates_leaves_no_temporary_file_and_replaces_the_old_one(tmp_path):
    path = tmp_path / "dates.json"
    save_upload_dates(path, {"a": "2026-10-01"})
    save_upload_dates(path, {"a": "2026-10-01", "b": "2026-10-02"})

    assert load_upload_dates(path) == {"a": "2026-10-01", "b": "2026-10-02"}
    assert [entry.name for entry in tmp_path.iterdir()] == ["dates.json"]


def test_pending_ids_are_the_extracted_ones_in_file_order_up_to_the_limit(tmp_path, capsys):
    processed_file = tmp_path / "processed.txt"
    processed_file.write_text("a\nb extracted\nc uploaded\nd extracted\ne extracted\n")

    playlist_watch.main(["pending", "--limit", "2", "--processed-file", str(processed_file)])

    assert capsys.readouterr().out == "b\nd\n"


def test_pending_prints_nothing_when_all_are_uploaded(tmp_path, capsys):
    processed_file = tmp_path / "processed.txt"
    processed_file.write_text("a uploaded\n")

    playlist_watch.main(["pending", "--limit", "5", "--processed-file", str(processed_file)])

    assert capsys.readouterr().out == ""
