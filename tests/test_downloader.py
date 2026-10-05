import importlib
import io
from pathlib import Path
from unittest import mock

import pytest
from tqdm import tqdm

from extract_memes import downloader
from extract_memes.downloader import SourceInfo, _progress_hook, download, fetch_source_info

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
    assert len(options["progress_hooks"]) == 1
    assert callable(options["progress_hooks"][0])
    add_paths.assert_called_once()
    ydl = youtube_dl.return_value.__enter__.return_value
    ydl.extract_info.assert_called_once_with(TEST_VIDEO_URL, download=True)
    assert result == Path("/fake/abc123_worst.mp4")


def test_url_download_passes_proxy_through(tmp_path, fake_ytdl):
    youtube_dl, _ = fake_ytdl

    download(TEST_VIDEO_URL, "worst", tmp_path, proxy="socks5h://127.0.0.1:1080")

    options = ydl_options(youtube_dl)
    assert options["proxy"] == "socks5h://127.0.0.1:1080"


def test_url_download_passes_progress_delta_to_yt_dlp_and_the_bar(tmp_path, fake_ytdl):
    youtube_dl, _ = fake_ytdl

    with mock.patch("extract_memes.downloader.tqdm", wraps=tqdm) as bar:
        download(TEST_VIDEO_URL, "worst", tmp_path, progress_delta=5.0)

    assert ydl_options(youtube_dl)["progress_delta"] == 5.0
    assert bar.call_args.kwargs["mininterval"] == 5.0


def test_url_download_leaves_progress_delta_unset_by_default(tmp_path, fake_ytdl):
    youtube_dl, _ = fake_ytdl

    with mock.patch("extract_memes.downloader.tqdm", wraps=tqdm) as bar:
        download(TEST_VIDEO_URL, "worst", tmp_path)

    assert "progress_delta" not in ydl_options(youtube_dl)
    assert "mininterval" not in bar.call_args.kwargs


def test_url_download_omits_proxy_when_not_given(tmp_path, fake_ytdl):
    youtube_dl, _ = fake_ytdl

    download(TEST_VIDEO_URL, "worst", tmp_path)

    options = ydl_options(youtube_dl)
    assert "proxy" not in options


def test_local_file_ignores_proxy(tmp_path, fake_ytdl):
    youtube_dl, _ = fake_ytdl
    video = tmp_path / "video.mp4"
    video.write_bytes(b"not really a video")

    assert download(str(video), "worst", tmp_path, proxy="socks5h://127.0.0.1:1080") == video
    youtube_dl.assert_not_called()


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


def test_fetch_source_info_reads_title_and_thumbnail_without_downloading(fake_ytdl):
    youtube_dl, _ = fake_ytdl
    ydl = youtube_dl.return_value.__enter__.return_value
    ydl.extract_info.return_value = {"title": "T", "thumbnail": "https://img/t.jpg"}

    info = fetch_source_info(TEST_VIDEO_URL, proxy="socks5h://127.0.0.1:1080")

    assert info == SourceInfo(title="T", thumbnail_url="https://img/t.jpg")
    ydl.extract_info.assert_called_once_with(TEST_VIDEO_URL, download=False)
    assert ydl_options(youtube_dl)["proxy"] == "socks5h://127.0.0.1:1080"


def test_fetch_source_info_is_none_for_a_local_file(tmp_path, fake_ytdl):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"")

    assert fetch_source_info(str(video)) is None
    fake_ytdl[0].assert_not_called()


def test_progress_hook_updates_the_bar_from_downloading_and_finished_events():
    bar = tqdm(file=io.StringIO())
    hook = _progress_hook(bar)

    hook({"status": "downloading", "total_bytes": 1000, "downloaded_bytes": 250})
    assert (bar.total, bar.n) == (1000, 250)

    hook({"status": "downloading", "total_bytes": 1000, "downloaded_bytes": 600})
    assert bar.n == 600

    hook({"status": "finished"})
    assert bar.n == bar.total == 1000

    bar.close()


def test_progress_hook_falls_back_to_the_estimated_total():
    bar = tqdm(file=io.StringIO())
    hook = _progress_hook(bar)

    hook({"status": "downloading", "total_bytes_estimate": 500, "downloaded_bytes": 100})

    assert (bar.total, bar.n) == (500, 100)
    bar.close()


def test_progress_hook_ignores_a_finished_event_with_no_known_total():
    bar = tqdm(file=io.StringIO())
    hook = _progress_hook(bar)

    hook({"status": "finished"})

    assert (bar.total, bar.n) == (None, 0)
    bar.close()


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
