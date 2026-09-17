import re
from pathlib import Path
from unittest import mock

import cv2
import numpy as np
import pytest

from extract_memes import pipeline
from extract_memes.classifier import FrameClassifier
from extract_memes.downloader import download
from extract_memes.pipeline import default_run_name, run

TEST_VIDEO_URL = "https://youtu.be/AElGyY97k_0"
MEME_NAME = re.compile(r"^frame_\d{6}_\d+\.\d{2}s\.jpg$")


class EveryNth(FrameClassifier):
    """Flags calls 0, n, 2n, …; records a copy of each frame it's given."""

    def __init__(self, n: int) -> None:
        self.n = n
        self.frames: list[np.ndarray] = []

    def is_meme_frame(self, frame: np.ndarray) -> bool:
        self.frames.append(frame.copy())
        return (len(self.frames) - 1) % self.n == 0

    def is_meme(self, image_path: Path) -> bool:
        raise AssertionError("the pipeline must classify frames in memory, not files")


class ReadsFiles(FrameClassifier):
    """Implements only `is_meme`, so each frame reaches it through a temporary file.

    Flags the first call, and raises on call `fail_on_call` if given.
    """

    def __init__(self, fail_on_call: int | None = None) -> None:
        self.fail_on_call = fail_on_call
        self.paths: list[Path] = []

    def is_meme(self, image_path: Path) -> bool:
        assert image_path.is_file()
        self.paths.append(image_path)
        if len(self.paths) == self.fail_on_call:
            raise RuntimeError("claude failed")
        return len(self.paths) == 1


class NeverMeme(FrameClassifier):
    def is_meme(self, image_path: Path) -> bool:
        return False


def image_height(path: Path) -> int:
    return cv2.imread(str(path)).shape[0]


def names(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.iterdir())


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

    run_dir = runtime_dir / "short"
    assert len(saved) == 8
    for path in saved:
        assert path.is_file()
        assert path.parent == run_dir / "high-res"
        assert MEME_NAME.match(path.name)
        assert cv2.imread(str(path)).shape[:2] == (144, 256)
    # The classifier gets every sample as a decoded array, and by default nothing but the memes is
    # written: no frames/, low-res/, or saved/.
    assert len(classifier.frames) == 79
    assert all(frame.shape == (144, 256, 3) for frame in classifier.frames)
    assert names(run_dir) == ["high-res"]


def test_save_frames_writes_every_sampled_frame(short_video, tmp_path):
    classifier = EveryNth(10)

    run(str(short_video), runtime_dir=tmp_path, fps=1.0, classifier=classifier, save_frames=True)

    frames = names(tmp_path / "short" / "frames")
    assert len(frames) == len(classifier.frames) == 79
    assert all(MEME_NAME.match(name) for name in frames)
    assert frames[:2] == ["frame_000000_0.00s.jpg", "frame_000025_1.00s.jpg"]


def test_save_frames_does_not_change_what_the_classifier_sees(short_video, tmp_path):
    in_memory, on_disk = EveryNth(7), EveryNth(7)
    kwargs = dict(runtime_dir=tmp_path, fps=1.0)

    without = run(str(short_video), run_name="without", classifier=in_memory, **kwargs)
    with_frames = run(str(short_video), run_name="with", classifier=on_disk, save_frames=True, **kwargs)

    assert [path.name for path in without] == [path.name for path in with_frames]
    assert len(in_memory.frames) == len(on_disk.frames) == 79
    assert all(np.array_equal(a, b) for a, b in zip(in_memory.frames, on_disk.frames))


def test_classifier_reading_files_leaves_no_temporary_files(short_video, tmp_path, temp_root):
    complete, aborted = ReadsFiles(), ReadsFiles(fail_on_call=3)

    saved = run(str(short_video), runtime_dir=tmp_path, run_name="complete", fps=0.5, classifier=complete)
    with pytest.raises(RuntimeError, match="claude failed"):
        run(str(short_video), runtime_dir=tmp_path, run_name="aborted", fps=0.5, classifier=aborted)

    assert len(saved) == 1
    assert len(complete.paths) == 40
    assert len(aborted.paths) == 3
    assert all(path.parent.parent == temp_root for path in complete.paths + aborted.paths)
    assert list(temp_root.iterdir()) == []
    assert names(tmp_path / "complete") == ["high-res"]
    assert names(tmp_path / "aborted") == ["high-res"]


def test_file_names_and_order(short_video, tmp_path):
    classifier = EveryNth(11)

    saved = run(
        str(short_video),
        runtime_dir=tmp_path,
        run_name="named",
        classifier=classifier,
        save_low_res=True,
    )

    # At 2 fps on 25 fps video the step is 12 frames (0.48 s): calls 0, 11, 22, … are flagged.
    expected = [f"frame_{12 * call:06d}_{12 * call / 25:.2f}s.jpg" for call in range(0, 164, 11)]
    assert [path.name for path in saved] == expected
    assert "frame_000264_10.56s.jpg" in expected
    assert names(tmp_path / "named" / "high-res") == expected
    # A low-res copy has exactly the name of its high-res copy, with no `thumb_` prefix.
    assert names(tmp_path / "named" / "low-res") == expected


def test_save_low_res_writes_a_scan_quality_copy_of_each_meme(short_video, tmp_path):
    kwargs = dict(runtime_dir=tmp_path, fps=1.0)

    default = run(str(short_video), run_name="default", classifier=EveryNth(10), **kwargs)
    saved = run(str(short_video), run_name="low", classifier=EveryNth(10), save_low_res=True, **kwargs)

    assert [path.name for path in saved] == [path.name for path in default]
    assert all(path.parent == tmp_path / "low" / "high-res" for path in saved)
    low_res = sorted((tmp_path / "low" / "low-res").iterdir())
    assert [path.name for path in low_res] == [path.name for path in saved]
    assert all(cv2.imread(str(path)).shape[:2] == (144, 256) for path in low_res)
    assert not (tmp_path / "default" / "low-res").exists()


@pytest.mark.parametrize("save_low_res", [False, True])
def test_no_memes(short_video, tmp_path, capsys, save_low_res):
    with mock.patch("extract_memes.pipeline.download", wraps=download) as download_spy:
        saved = run(
            str(short_video),
            downloads_dir=tmp_path / "downloads",
            runtime_dir=tmp_path / ".runtime",
            classifier=NeverMeme(),
            save_low_res=save_low_res,
        )

    assert saved == []
    assert capsys.readouterr().out == "No memes found.\n"
    assert [call.args[1] for call in download_spy.call_args_list] == ["worst"]
    # high-res/ always exists and low-res/ only when asked for; both stay empty.
    run_dir = tmp_path / ".runtime" / "short"
    assert names(run_dir) == (["high-res", "low-res"] if save_low_res else ["high-res"])
    assert all(names(folder) == [] for folder in run_dir.iterdir())


def test_default_classifier_is_heuristic(short_video, tmp_path):
    with (
        mock.patch("extract_memes.pipeline.HeuristicClassifier") as heuristic_classifier,
        mock.patch("extract_memes.pipeline.ClaudeCliClassifier") as claude_classifier,
    ):
        heuristic_classifier.return_value.is_meme_frame.return_value = False
        run(str(short_video), runtime_dir=tmp_path, fps=0.5)

    heuristic_classifier.assert_called_once_with()
    claude_classifier.assert_not_called()
    assert heuristic_classifier.return_value.is_meme_frame.call_count == 40
    heuristic_classifier.return_value.is_meme.assert_not_called()


def test_claude_classifier_type_uses_model_and_effort(short_video, tmp_path):
    with mock.patch("extract_memes.pipeline.ClaudeCliClassifier") as claude_classifier:
        claude_classifier.return_value.is_meme_frame.return_value = False
        run(
            str(short_video),
            runtime_dir=tmp_path,
            fps=0.5,
            classifier_model="claude-sonnet-5",
            classifier_effort=None,
            classifier_type="claude",
        )

    claude_classifier.assert_called_once_with(model="claude-sonnet-5", effort=None)
    assert claude_classifier.return_value.is_meme_frame.call_count == 40


def test_unknown_classifier_type_raises_before_creating_anything(short_video, tmp_path):
    with (
        mock.patch("extract_memes.pipeline.download", side_effect=AssertionError("downloaded")),
        pytest.raises(ValueError, match="heuristic.*claude"),
    ):
        run(str(short_video), runtime_dir=tmp_path, classifier_type="clip")

    assert list(tmp_path.iterdir()) == []


def test_injected_classifier_ignores_classifier_options(short_video, tmp_path):
    with (
        mock.patch("extract_memes.pipeline.HeuristicClassifier") as heuristic_classifier,
        mock.patch("extract_memes.pipeline.ClaudeCliClassifier") as claude_classifier,
    ):
        run(
            str(short_video),
            runtime_dir=tmp_path,
            fps=0.5,
            classifier=NeverMeme(),
            classifier_type="bogus",
        )

    heuristic_classifier.assert_not_called()
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
    run_dir = tmp_path / "again"
    first = run(str(short_video), classifier=EveryNth(10), save_low_res=True, **kwargs)
    first_low_res = names(run_dir / "low-res")
    extra = run_dir / "high-res" / "keep-me.txt"
    extra.write_text("not written by the pipeline")
    # A folder left by a run made before the high-res/low-res layout.
    old = run_dir / "saved" / "thumb_frame_000000_0.00s.jpg"
    old.parent.mkdir()
    old.write_text("old layout")

    second = run(str(short_video), classifier=EveryNth(20), **kwargs)

    assert extra.is_file()
    assert all(path.is_file() for path in first)
    assert set(second) < set(first)
    assert old.read_text() == "old layout"
    assert names(run_dir / "saved") == [old.name]
    # A run without save_low_res leaves earlier low-res copies alone.
    assert len(first_low_res) == 4
    assert names(run_dir / "low-res") == first_low_res


def test_classifier_error_aborts_the_run(short_video, tmp_path):
    classifier = mock.Mock(spec=FrameClassifier)
    classifier.is_meme_frame.side_effect = [True, False, RuntimeError("claude failed")]

    with pytest.raises(RuntimeError, match="claude failed"):
        run(str(short_video), runtime_dir=tmp_path, run_name="broken", classifier=classifier)

    classifier.is_meme.assert_not_called()
    assert names(tmp_path / "broken") == ["high-res"]
    assert names(tmp_path / "broken" / "high-res") == []


def test_classifier_error_keeps_saved_frames_and_low_res_copies(short_video, tmp_path):
    classifier = mock.Mock(spec=FrameClassifier)
    classifier.is_meme_frame.side_effect = [True, False, RuntimeError("claude failed")]

    with pytest.raises(RuntimeError, match="claude failed"):
        run(
            str(short_video),
            runtime_dir=tmp_path,
            run_name="broken",
            classifier=classifier,
            save_frames=True,
            save_low_res=True,
        )

    run_dir = tmp_path / "broken"
    # Each frame is written before it's classified, so the frame that failed is kept too.
    assert names(run_dir / "frames") == [
        "frame_000000_0.00s.jpg",
        "frame_000012_0.48s.jpg",
        "frame_000024_0.96s.jpg",
    ]
    assert names(run_dir / "low-res") == ["frame_000000_0.00s.jpg"]
    assert names(run_dir / "high-res") == []


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


@pytest.mark.parametrize("save_frames", [False, True])
def test_default_run_finds_exactly_the_known_memes(short_video, tmp_path, save_frames):
    saved = run(str(short_video), downloads_dir=tmp_path, runtime_dir=tmp_path, save_frames=save_frames)

    high_res_dir = tmp_path / "short" / "high-res"
    assert saved == [
        high_res_dir / "frame_000264_10.56s.jpg",
        high_res_dir / "frame_000720_28.80s.jpg",
    ]
    assert all(path.is_file() for path in saved)
    assert (tmp_path / "short" / "frames").is_dir() == save_frames


@pytest.mark.slow
def test_real_url_mock_classifier_run(tmp_path):
    downloads_dir = tmp_path / "downloads"

    saved = run(
        TEST_VIDEO_URL,
        downloads_dir=downloads_dir,
        runtime_dir=tmp_path / ".runtime",
        classifier=EveryNth(5),
        save_low_res=True,
    )

    assert len(saved) == 6
    for path in saved:
        assert path.is_file()
        low_res = path.parent.parent / "low-res" / path.name
        assert image_height(path) > image_height(low_res)
    downloaded = [path.name for path in downloads_dir.rglob("*")]
    assert sorted(downloaded) == ["AElGyY97k_0_best.mp4", "AElGyY97k_0_worst.mp4"]
    assert not any("*" in name for name in downloaded)

@pytest.mark.slow
def test_real_url_real_classifier_run(tmp_path):
    downloads_dir = tmp_path / "downloads"

    saved = run(
        TEST_VIDEO_URL,
        downloads_dir=downloads_dir,
        runtime_dir=tmp_path / ".runtime",
        save_low_res=True,
    )

    assert len(saved) == 2
    for path in saved:
        assert path.is_file()
        low_res = path.parent.parent / "low-res" / path.name
        assert image_height(path) > image_height(low_res)
    downloaded = [path.name for path in downloads_dir.rglob("*")]
    assert sorted(downloaded) == ["AElGyY97k_0_best.mp4", "AElGyY97k_0_worst.mp4"]
    assert not any("*" in name for name in downloaded)
