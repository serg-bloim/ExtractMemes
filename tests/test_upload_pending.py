from pathlib import Path

import pytest

from extract_memes import upload_pending
from extract_memes.downloader import SourceInfo
from extract_memes.upload_pending import pending_video_ids, upload_pending as run_upload
from extract_memes.uploader import Uploader


class FakeUploader(Uploader):
    def __init__(self, fail_on: str | None = None) -> None:
        self.calls: list[tuple[list[str], str, SourceInfo | None]] = []
        self.fail_on = fail_on

    def upload_all(self, image_paths: list[Path], source: str, info: SourceInfo | None = None) -> None:
        if self.fail_on and self.fail_on in source:
            raise RuntimeError("upload failed")
        self.calls.append(([p.name for p in image_paths], source, info))


def _clean(runs_dir: Path, video_id: str, count: int) -> None:
    folder = runs_dir / video_id / "clean"
    folder.mkdir(parents=True)
    for number in range(1, count + 1):
        (folder / f"meme_{number:03d}.png").write_bytes(b"png")


def _info(source: str) -> SourceInfo:
    return SourceInfo(title="title of " + source)


def test_pending_video_ids_are_the_extracted_ones_in_file_order_up_to_the_limit():
    processed = {"a": "uploaded", "b": "extracted", "c": "extracted", "d": "extracted"}

    assert pending_video_ids(processed, limit=2) == ["b", "c"]


def test_uploads_each_pending_video_and_reports_it(tmp_path):
    processed_file = tmp_path / "processed.txt"
    processed_file.write_text("old\nb extracted\nc extracted\n")
    _clean(tmp_path, "b", 2)
    _clean(tmp_path, "c", 1)
    uploader, done = FakeUploader(), []

    uploaded = run_upload(processed_file, tmp_path, uploader, on_uploaded=done.append, fetch_info=_info)

    assert uploaded == done == ["b", "c"]
    assert uploader.calls == [
        (["meme_001.png", "meme_002.png"], "https://youtu.be/b", SourceInfo(title="title of https://youtu.be/b")),
        (["meme_001.png"], "https://youtu.be/c", SourceInfo(title="title of https://youtu.be/c")),
    ]


def test_at_most_limit_videos_per_run(tmp_path):
    processed_file = tmp_path / "processed.txt"
    processed_file.write_text("".join(f"v{n} extracted\n" for n in range(8)))
    for n in range(8):
        _clean(tmp_path, f"v{n}", 1)

    uploaded = run_upload(processed_file, tmp_path, FakeUploader(), limit=5, fetch_info=_info)

    assert uploaded == ["v0", "v1", "v2", "v3", "v4"]


def test_a_failure_stops_the_run_and_only_earlier_videos_are_reported(tmp_path):
    processed_file = tmp_path / "processed.txt"
    processed_file.write_text("a extracted\nb extracted\nc extracted\n")
    for video_id in "abc":
        _clean(tmp_path, video_id, 1)
    done = []

    with pytest.raises(RuntimeError, match="upload failed"):
        run_upload(processed_file, tmp_path, FakeUploader(fail_on="/b"), on_uploaded=done.append, fetch_info=_info)

    assert done == ["a"]


def test_a_video_without_clean_images_is_reported_without_uploading(tmp_path):
    processed_file = tmp_path / "processed.txt"
    processed_file.write_text("a extracted\n")
    uploader, done = FakeUploader(), []

    run_upload(processed_file, tmp_path, uploader, on_uploaded=done.append, fetch_info=_info)

    assert uploader.calls == []
    assert done == ["a"]


def test_a_failed_info_fetch_still_uploads_without_info(tmp_path):
    processed_file = tmp_path / "processed.txt"
    processed_file.write_text("a extracted\n")
    _clean(tmp_path, "a", 1)
    uploader = FakeUploader()

    def broken(source: str):
        raise RuntimeError("no network")

    run_upload(processed_file, tmp_path, uploader, fetch_info=broken)

    assert uploader.calls == [(["meme_001.png"], "https://youtu.be/a", None)]


def test_nothing_pending_does_nothing(tmp_path):
    processed_file = tmp_path / "processed.txt"
    processed_file.write_text("a uploaded\n")
    uploader = FakeUploader()

    assert run_upload(processed_file, tmp_path, uploader, fetch_info=_info) == []
    assert uploader.calls == []


def test_main_appends_each_uploaded_id_to_the_done_file(tmp_path, monkeypatch):
    processed_file = tmp_path / "processed.txt"
    processed_file.write_text("a extracted\nb extracted\n")
    _clean(tmp_path, "a", 1)
    _clean(tmp_path, "b", 1)
    uploader = FakeUploader()
    monkeypatch.setattr(upload_pending, "TelegramUploader", lambda: uploader)
    monkeypatch.setattr(upload_pending, "fetch_source_info", lambda source, proxy=None: None)
    done_file = tmp_path / "out" / "done.txt"

    upload_pending.main(
        ["--processed-file", str(processed_file), "--runs-dir", str(tmp_path), "--done-file", str(done_file)]
    )

    assert done_file.read_text() == "a\nb\n"
