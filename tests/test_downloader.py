import importlib
from pathlib import Path
from unittest import mock

import pytest

from extract_memes import downloader
from extract_memes.downloader import download

TEST_VIDEO_URL = "https://youtu.be/AElGyY97k_0"


@pytest.fixture
def fake_ytdl():
    """Patch yt-dlp and static-ffmpeg; yields (YoutubeDL mock, add_paths mock)."""
    with (
        mock.patch("yt_dlp.YoutubeDL") as youtube_dl,
        mock.patch("static_ffmpeg.add_paths") as add_paths,
    ):
        ydl = youtube_dl.return_value.__enter__.return_value
        ydl.extract_info.return_value = {"id": "abc123", "ext": "mp4"}
        ydl.prepare_filename.side_effect = lambda info: "/fake/abc123_worst.mp4"
        yield youtube_dl, add_paths


def ydl_options(youtube_dl) -> dict:
    youtube_dl.assert_called_once()
    return youtube_dl.call_args.args[0]


def test_local_file_is_passed_through(tmp_path, fake_ytdl):
    youtube_dl, add_paths = fake_ytdl
    video = tmp_path / "video.mp4"
    video.write_bytes(b"not really a video")
    dest_dir = tmp_path / "downloads"

    assert download(str(video), "worst", dest_dir) == video
    assert download(str(video), "best", dest_dir) == video
    youtube_dl.assert_not_called()
    add_paths.assert_not_called()
    assert not dest_dir.exists()


@pytest.mark.parametrize(
    ("quality", "selector"),
    [("worst", "wv*[ext=mp4]/wv*"), ("best", "bv*[ext=mp4]/bv*")],
)
def test_url_download_options(tmp_path, fake_ytdl, quality, selector):
    youtube_dl, add_paths = fake_ytdl

    result = download(TEST_VIDEO_URL, quality, tmp_path)

    options = ydl_options(youtube_dl)
    assert options["format"] == selector
    assert options["outtmpl"].endswith(f"%(id)s_{quality}.%(ext)s")
    assert Path(options["outtmpl"]).parent == tmp_path
    assert "*" not in options["outtmpl"]
    assert options["js_runtimes"] == {"node": {}}
    assert options["quiet"] is True
    assert options["noprogress"] is True
    add_paths.assert_called_once()
    ydl = youtube_dl.return_value.__enter__.return_value
    ydl.extract_info.assert_called_once_with(TEST_VIDEO_URL, download=True)
    assert result == Path("/fake/abc123_worst.mp4")


def test_url_download_creates_dest_dir(tmp_path, fake_ytdl):
    dest_dir = tmp_path / "nested" / "downloads"

    download(TEST_VIDEO_URL, "worst", dest_dir)

    assert dest_dir.is_dir()


def test_yt_dlp_failure_raises_runtime_error(tmp_path, fake_ytdl):
    youtube_dl, _ = fake_ytdl
    ydl = youtube_dl.return_value.__enter__.return_value
    error = Exception("Requested format is not available")
    ydl.extract_info.side_effect = error

    with pytest.raises(RuntimeError, match="not-a-real-file.mp4") as excinfo:
        download("not-a-real-file.mp4", "best", tmp_path)

    assert "best" in str(excinfo.value)
    assert excinfo.value.__cause__ is error


def test_importing_module_does_not_set_up_ffmpeg():
    with mock.patch("static_ffmpeg.add_paths") as add_paths:
        importlib.reload(downloader)
    add_paths.assert_not_called()


@pytest.fixture(scope="module")
def real_downloads(tmp_path_factory):
    dest_dir = tmp_path_factory.mktemp("downloads")
    return {quality: download(TEST_VIDEO_URL, quality, dest_dir) for quality in ("worst", "best")}


@pytest.mark.slow
@pytest.mark.parametrize("quality", ["worst", "best"])
def test_real_download(real_downloads, quality):
    import cv2

    path = real_downloads[quality]
    assert path.is_file()
    assert path.stat().st_size > 0
    assert path.suffix == ".mp4"
    assert path.name == f"AElGyY97k_0_{quality}.mp4"
    assert path.read_bytes()[4:8] == b"ftyp"
    capture = cv2.VideoCapture(str(path))
    try:
        assert capture.isOpened()
    finally:
        capture.release()


@pytest.mark.slow
def test_real_download_best_is_at_least_as_tall_as_worst(real_downloads):
    import cv2

    def frame_height(path: Path) -> float:
        capture = cv2.VideoCapture(str(path))
        try:
            return capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
        finally:
            capture.release()

    assert frame_height(real_downloads["best"]) >= frame_height(real_downloads["worst"])
