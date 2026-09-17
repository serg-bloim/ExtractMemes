import re
from pathlib import Path
from unittest import mock

import cv2
import pytest

from extract_memes import pipeline
from extract_memes.classifier import FrameClassifier
from extract_memes.downloader import download
from extract_memes.pipeline import default_run_name, run

TEST_VIDEO_URL = "https://youtu.be/AElGyY97k_0"
MEME_NAME = re.compile(r"^frame_\d{6}_\d+\.\d{2}s\.jpg$")


class EveryNth(FrameClassifier):
    """Flags calls 0, n, 2n, …; records each image path and whether it existed when classified."""

    def __init__(self, n: int) -> None:
        self.n = n
        self.calls: list[tuple[Path, bool]] = []

    def is_meme(self, image_path: Path) -> bool:
        self.calls.append((image_path, image_path.is_file()))
        return (len(self.calls) - 1) % self.n == 0


class NeverMeme(FrameClassifier):
    def is_meme(self, image_path: Path) -> bool:
        return False


def image_height(path: Path) -> int:
    return cv2.imread(str(path)).shape[0]


def test_local_run(short_video, tmp_path):
    classifier = EveryNth(10)
    runtime_dir = tmp_path / ".runtime"

    with (
        mock.patch("yt_dlp.YoutubeDL", side_effect=AssertionError("network access")),
        mock.patch("static_ffmpeg.add_paths", side_effect=AssertionError("ffmpeg setup")),
    ):
        saved = run(
            str(short_video),
            downloads_dir=tmp_path / "downloads",
            runtime_dir=runtime_dir,
            fps=1.0,
            classifier=classifier,
        )

    saved_dir = runtime_dir / "short" / "saved"
    frames_dir = runtime_dir / "short" / "frames"
    assert len(saved) == 8
    for path in saved:
        assert path.is_file()
        assert path.parent == saved_dir
        assert MEME_NAME.match(path.name)
        assert cv2.imread(str(path)).shape[:2] == (144, 256)
    assert len(list(frames_dir.glob("*.jpg"))) == len(classifier.calls)
    assert len(list(saved_dir.glob("thumb_frame_*.jpg"))) == len(saved)
    # The classifier sees each frame after it's written to frames/.
    assert all(path.parent == frames_dir and existed for path, existed in classifier.calls)


def test_file_names_and_order(short_video, tmp_path):
    classifier = EveryNth(11)

    saved = run(str(short_video), runtime_dir=tmp_path, run_name="named", classifier=classifier)

    # At 2 fps on 25 fps video the step is 12 frames (0.48 s): calls 0, 11, 22, … are flagged.
    expected = [f"frame_{12 * call:06d}_{12 * call / 25:.2f}s.jpg" for call in range(0, 164, 11)]
    assert [path.name for path in saved] == expected
    assert "frame_000264_10.56s.jpg" in expected
    saved_dir = tmp_path / "named" / "saved"
    assert sorted(path.name for path in saved_dir.glob("thumb_*")) == [f"thumb_{name}" for name in expected]
    frames = sorted(path.name for path in (tmp_path / "named" / "frames").iterdir())
    assert len(frames) == 164
    assert frames[:2] == ["frame_000000_0.00s.jpg", "frame_000012_0.48s.jpg"]


def test_no_memes(short_video, tmp_path, capsys):
    with mock.patch("extract_memes.pipeline.download", wraps=download) as download_spy:
        saved = run(
            str(short_video),
            downloads_dir=tmp_path / "downloads",
            runtime_dir=tmp_path / ".runtime",
            classifier=NeverMeme(),
        )

    assert saved == []
    assert capsys.readouterr().out == "No memes found.\n"
    assert [call.args[1] for call in download_spy.call_args_list] == ["worst"]
    assert list((tmp_path / ".runtime" / "short" / "saved").iterdir()) == []


def test_default_classifier_uses_model_and_effort(short_video, tmp_path):
    with mock.patch("extract_memes.pipeline.ClaudeCliClassifier") as claude_classifier:
        claude_classifier.return_value.is_meme.return_value = False
        run(
            str(short_video),
            runtime_dir=tmp_path,
            fps=0.5,
            classifier_model="claude-sonnet-5",
            classifier_effort=None,
        )

    claude_classifier.assert_called_once_with(model="claude-sonnet-5", effort=None)
    assert claude_classifier.return_value.is_meme.call_count == 40


def test_injected_classifier_ignores_model_and_effort(short_video, tmp_path):
    with mock.patch("extract_memes.pipeline.ClaudeCliClassifier") as claude_classifier:
        run(str(short_video), runtime_dir=tmp_path, fps=0.5, classifier=NeverMeme())

    claude_classifier.assert_not_called()


def test_progress_bars(short_video, tmp_path):
    with mock.patch("extract_memes.pipeline.tqdm", wraps=pipeline.tqdm) as progress:
        run(str(short_video), runtime_dir=tmp_path, fps=0.5, classifier=EveryNth(10))

    assert [call.kwargs["desc"] for call in progress.call_args_list] == [
        "Scanning frames",
        "Extracting memes",
    ]


def test_rerun_overwrites_and_keeps_other_files(short_video, tmp_path):
    kwargs = dict(runtime_dir=tmp_path, run_name="again", fps=0.5)
    first = run(str(short_video), classifier=EveryNth(10), **kwargs)
    extra = tmp_path / "again" / "saved" / "keep-me.txt"
    extra.write_text("not written by the pipeline")

    second = run(str(short_video), classifier=EveryNth(20), **kwargs)

    assert extra.is_file()
    assert all(path.is_file() for path in first)
    assert set(second) < set(first)


def test_classifier_error_aborts_and_keeps_written_files(short_video, tmp_path):
    classifier = mock.Mock(spec=FrameClassifier)
    classifier.is_meme.side_effect = [True, False, RuntimeError("claude failed")]

    with pytest.raises(RuntimeError, match="claude failed"):
        run(str(short_video), runtime_dir=tmp_path, run_name="broken", classifier=classifier)

    assert len(list((tmp_path / "broken" / "frames").iterdir())) == 3
    assert [path.name for path in (tmp_path / "broken" / "saved").iterdir()] == [
        "thumb_frame_000000_0.00s.jpg"
    ]


def test_download_error_propagates(tmp_path):
    with (
        mock.patch("extract_memes.pipeline.download", side_effect=RuntimeError("no such video")),
        pytest.raises(RuntimeError, match="no such video"),
    ):
        run(TEST_VIDEO_URL, runtime_dir=tmp_path, classifier=NeverMeme())


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("sample/short.mp4", "short"),
        ("https://youtu.be/AElGyY97k_0", "AElGyY97k_0"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/abc123", "abc123"),
        ("https://www.youtube.com/watch?list=PL1&v=dQw4w9WgXcQ&t=42s", "dQw4w9WgXcQ"),
        ("https://youtu.be/", "youtu_be"),
        ("videos/my clip (final).mp4", "my_clip_final"),
        ("!!!.mp4", "video"),
        ("https://example.com/!!!", "video"),
    ],
)
def test_default_run_name(source, expected):
    assert default_run_name(source) == expected


@pytest.mark.slow
def test_real_url_run(tmp_path):
    downloads_dir = tmp_path / "downloads"

    saved = run(
        TEST_VIDEO_URL,
        downloads_dir=downloads_dir,
        runtime_dir=tmp_path / ".runtime",
        classifier=EveryNth(5),
    )

    assert len(saved) == 6
    for path in saved:
        assert path.is_file()
        thumbnail = path.with_name(f"thumb_{path.name}")
        assert image_height(path) > image_height(thumbnail)
    downloaded = [path.name for path in downloads_dir.rglob("*")]
    assert sorted(downloaded) == ["AElGyY97k_0_best.mp4", "AElGyY97k_0_worst.mp4"]
    assert not any("*" in name for name in downloaded)
