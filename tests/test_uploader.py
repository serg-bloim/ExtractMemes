from pathlib import Path

import pytest

from extract_memes.downloader import SourceInfo
from extract_memes.uploader import Uploader


class Recorder(Uploader):
    def __init__(self) -> None:
        self.calls: list[tuple[list[Path], str]] = []

    def upload_all(self, image_paths: list[Path], source: str, info: SourceInfo | None = None) -> None:
        self.calls.append((list(image_paths), source))


def test_uploader_is_abstract():
    with pytest.raises(TypeError):
        Uploader()


def test_recorder_records_the_call():
    recorder = Recorder()
    paths = [Path("a.jpg"), Path("b.jpg"), Path("c.jpg")]

    recorder.upload_all(paths, "https://youtu.be/xyz")

    assert recorder.calls == [(paths, "https://youtu.be/xyz")]
