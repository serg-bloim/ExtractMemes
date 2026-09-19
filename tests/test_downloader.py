import importlib
import io
from pathlib import Path
from unittest import mock

import pytest
from tqdm import tqdm

from extract_memes import downloader
from extract_memes.downloader import (
    SECTION_ENCODE_ARGS,
    _progress_hook,
    _section_progress_hook,
    download,
    download_sections,
)

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


@pytest.fixture
def fake_ytdl_sections(fake_ytdl):
    """`fake_ytdl`, with `extract_info` returning two finished sections."""
    youtube_dl, add_paths = fake_ytdl
    ydl = youtube_dl.return_value.__enter__.return_value
    ydl.extract_info.return_value = {
        "id": "abc123",
        "ext": "mp4",
        "requested_downloads": [
            {"filepath": "/fake/abc123_best_9-13.mp4", "section_start": 9.0, "section_end": 13.0},
            {"filepath": "/fake/abc123_best_27-31.mp4", "section_start": 27.0, "section_end": 31.0},
        ],
    }
    return youtube_dl, add_paths


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


def test_section_download_options(tmp_path, fake_ytdl_sections):
    youtube_dl, add_paths = fake_ytdl_sections

    result = download_sections(TEST_VIDEO_URL, [(9, 13), (27, 31)], tmp_path)

    options = ydl_options(youtube_dl)
    assert options["format"] == "bv*[ext=mp4][protocol=https]"
    assert options["outtmpl"].endswith("%(id)s_best_%(section_start)d-%(section_end)d.%(ext)s")
    assert Path(options["outtmpl"]).parent == tmp_path
    assert "*" not in options["outtmpl"]
    assert options["force_keyframes_at_cuts"] is True
    assert options["external_downloader_args"] == {"ffmpeg_o": SECTION_ENCODE_ARGS}
    assert options["js_runtimes"] == {"node": {}}
    assert options["quiet"] is True
    assert options["noprogress"] is True
    assert len(options["progress_hooks"]) == 1
    add_paths.assert_called_once()
    ydl = youtube_dl.return_value.__enter__.return_value
    ydl.extract_info.assert_called_once_with(TEST_VIDEO_URL, download=True)
    assert result == [
        (Path("/fake/abc123_best_9-13.mp4"), 9.0),
        (Path("/fake/abc123_best_27-31.mp4"), 27.0),
    ]


def test_section_download_requests_each_range(tmp_path, fake_ytdl_sections):
    youtube_dl, _ = fake_ytdl_sections

    download_sections(TEST_VIDEO_URL, [(9, 13), (27, 31)], tmp_path)

    ranges = ydl_options(youtube_dl)["download_ranges"]
    assert ranges({}, None) == [
        {"start_time": 9.0, "end_time": 13.0, "index": 0},
        {"start_time": 27.0, "end_time": 31.0, "index": 1},
    ]


def test_section_download_needs_at_least_one_range(tmp_path, fake_ytdl):
    youtube_dl, add_paths = fake_ytdl

    with pytest.raises(ValueError, match="at least one range"):
        download_sections(TEST_VIDEO_URL, [], tmp_path)

    youtube_dl.assert_not_called()
    add_paths.assert_not_called()


def test_section_download_creates_dest_dir(tmp_path, fake_ytdl_sections):
    dest_dir = tmp_path / "nested" / "downloads"

    download_sections(TEST_VIDEO_URL, [(9, 13), (27, 31)], dest_dir)

    assert dest_dir.is_dir()


def test_section_download_failure_raises_runtime_error(tmp_path, fake_ytdl_sections):
    youtube_dl, _ = fake_ytdl_sections
    ydl = youtube_dl.return_value.__enter__.return_value
    error = Exception("Requested format is not available")
    ydl.extract_info.side_effect = error

    with pytest.raises(RuntimeError, match="AElGyY97k_0") as excinfo:
        download_sections(TEST_VIDEO_URL, [(9, 13)], tmp_path)

    assert "(9, 13)" in str(excinfo.value)
    assert excinfo.value.__cause__ is error


def test_section_download_bridges_a_socks_proxy_for_ffmpeg(tmp_path, fake_ytdl_sections):
    youtube_dl, _ = fake_ytdl_sections

    download_sections(TEST_VIDEO_URL, [(9, 13)], tmp_path, proxy="socks5h://127.0.0.1:1080")

    options = ydl_options(youtube_dl)
    # yt-dlp keeps speaking SOCKS; only ffmpeg, which cannot, is pointed at the loopback bridge.
    assert options["proxy"] == "socks5h://127.0.0.1:1080"
    flag, bridge_url = options["external_downloader_args"]["ffmpeg_i"]
    assert flag == "-http_proxy"
    assert bridge_url.startswith("http://127.0.0.1:")


@pytest.mark.parametrize("proxy", [None, "http://127.0.0.1:3128"])
def test_section_download_does_not_bridge_a_usable_proxy(tmp_path, fake_ytdl_sections, proxy):
    youtube_dl, _ = fake_ytdl_sections

    download_sections(TEST_VIDEO_URL, [(9, 13)], tmp_path, proxy=proxy)

    options = ydl_options(youtube_dl)
    assert "ffmpeg_i" not in options["external_downloader_args"]
    assert options.get("proxy") == proxy


def test_section_progress_hook_counts_finished_sections():
    bar = tqdm(total=2, file=io.StringIO())
    hook = _section_progress_hook(bar)

    hook({"status": "downloading", "downloaded_bytes": 100})
    assert bar.n == 0

    hook({"status": "finished"})
    hook({"status": "finished"})
    assert bar.n == 2

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


# The test video runs 12.08s, so every section has to fit inside that.
REAL_SECTION_RANGES = [(2, 5), (8, 11)]


@pytest.fixture(scope="module")
def real_sections(tmp_path_factory):
    dest_dir = tmp_path_factory.mktemp("sections")
    return download_sections(TEST_VIDEO_URL, REAL_SECTION_RANGES, dest_dir)


@pytest.mark.slow
@pytest.mark.parametrize("index", range(len(REAL_SECTION_RANGES)))
def test_real_section_download(real_sections, index):
    import cv2

    start, end = REAL_SECTION_RANGES[index]
    path, reported_start = real_sections[index]
    assert path.is_file()
    assert path.name == f"AElGyY97k_0_best_{start}-{end}.mp4"
    assert path.read_bytes()[4:8] == b"ftyp"
    assert reported_start == start
    capture = cv2.VideoCapture(str(path))
    try:
        assert capture.isOpened()
        duration = capture.get(cv2.CAP_PROP_FRAME_COUNT) / capture.get(cv2.CAP_PROP_FPS)
    finally:
        capture.release()
    assert duration == pytest.approx(end - start, abs=0.5)


@pytest.mark.slow
@pytest.mark.parametrize("index", range(len(REAL_SECTION_RANGES)))
def test_real_section_frames_line_up_with_the_whole_video(real_sections, real_downloads, index):
    """A section's frame at `t - section_start` must be the whole video's frame at `t`.

    This is what the pipeline's timecodes and frame names rest on, so it's checked two ways: the
    frames have to be close in absolute terms, and they have to be closer than the frames a second
    either side — which a cut that slipped back to the previous keyframe would fail.
    """
    import numpy as np

    from extract_memes.frame_extractor import frame_at

    path, section_start = real_sections[index]
    timestamp = section_start + 1.5

    def difference(offset: float) -> float:
        whole = frame_at(real_downloads["best"], timestamp + offset).astype(np.int16)
        return float(np.abs(whole - section_frame).mean())

    section_frame = frame_at(path, timestamp - section_start).astype(np.int16)
    aligned = difference(0.0)
    assert aligned < 12.0
    assert aligned <= min(difference(-1.0), difference(1.0)) + 1.0
