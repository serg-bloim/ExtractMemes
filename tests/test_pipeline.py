import re
from pathlib import Path
from unittest import mock

import cv2
import numpy as np
import pytest

from extract_memes import pipeline
from extract_memes.batch_cleaner import banding_score
from extract_memes.classifier import FrameClassifier
from extract_memes.downloader import download
from extract_memes.pipeline import MEME_LABEL, default_run_name, format_timecode, run
from extract_memes.timecode_sender import TimecodeSender
from extract_memes.downloader import SourceInfo
from extract_memes.frame_extractor import sample_frames
from extract_memes.uploader import Uploader

TEST_VIDEO_URL = "https://youtu.be/AElGyY97k_0"
MEME_NAME = re.compile(r"^frame_\d{6}_\d+\.\d{2}s\.jpg$")
TIMECODE_LINE = re.compile(r"^(\d+:)?\d?\d:\d\d Мем \d+$")
BATCH_NAME = re.compile(r"^meme_\d{3}$")


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


class FlagsScanCalls(FrameClassifier):
    """Flags the given scan calls (numbered from 0), then every call once the scan is over.

    Records each frame it's given, so a test can count the extraction pass's frames.
    """

    def __init__(self, flagged: set[int], scan_calls: int) -> None:
        self.flagged = flagged
        self.scan_calls = scan_calls
        self.calls = 0

    def is_meme_frame(self, frame: np.ndarray) -> bool:
        call = self.calls
        self.calls += 1
        return call in self.flagged or call >= self.scan_calls

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


class FakeUploader(Uploader):
    """Records each `upload_all` call; raises `error` (if given) after recording it."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[list[Path], str]] = []
        self.infos: list[SourceInfo | None] = []

    def upload_all(self, image_paths: list[Path], source: str, info: SourceInfo | None = None) -> None:
        self.calls.append((list(image_paths), source))
        self.infos.append(info)
        if self.error:
            raise self.error


class FakeTimecodeSender(TimecodeSender):
    """Records each `send` call; raises `error` (if given) after recording it."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[list[str], str]] = []

    def send(self, timecodes: list[str], source: str) -> None:
        self.calls.append((list(timecodes), source))
        if self.error:
            raise self.error


def image_height(path: Path) -> int:
    return cv2.imread(str(path)).shape[0]


def names(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.iterdir())


def batches(run_dir: Path) -> list[Path]:
    """The `high-res/meme_<n>/` batch folders of a run, in meme order."""
    return sorted((run_dir / "high-res").iterdir())


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
            save_high_res=True,
        )

    run_dir = runtime_dir / "short"
    # Eight scan hits, so eight batch folders, each combined into one cleaned image.
    assert [path.name for path in batches(run_dir)] == [f"meme_{n:03d}" for n in range(1, 9)]
    assert saved == [run_dir / "clean" / f"meme_{n:03d}.png" for n in range(1, 9)]
    for path in saved:
        assert path.is_file()
        assert cv2.imread(str(path)).shape[:2] == (144, 256)
    for batch in batches(run_dir):
        assert batch.iterdir()
        for path in batch.iterdir():
            assert MEME_NAME.match(path.name)
            assert cv2.imread(str(path)).shape[:2] == (144, 256)
    # The classifier gets every sample as a decoded array during the scan, then every frame of
    # each batch. By default nothing but the memes is written: no frames/, low-res/, or saved/.
    assert len(classifier.frames) > 79
    assert all(frame.shape == (144, 256, 3) for frame in classifier.frames)
    assert names(run_dir) == ["clean", "high-res"]


def test_clean_method_none_returns_the_batch_frames(short_video, tmp_path):
    classifier = EveryNth(10)

    saved = run(
        str(short_video),
        runtime_dir=tmp_path,
        run_name="raw",
        fps=1.0,
        classifier=classifier,
        clean_method=None,
        save_high_res=True,
    )

    run_dir = tmp_path / "raw"
    assert names(run_dir) == ["high-res"]
    assert saved == [path for batch in batches(run_dir) for path in sorted(batch.iterdir())]


def test_high_res_frames_are_not_kept_by_default(short_video, tmp_path):
    saved = run(str(short_video), runtime_dir=tmp_path, run_name="lean", fps=1.0, classifier=EveryNth(10))

    run_dir = tmp_path / "lean"
    assert names(run_dir) == ["clean"]
    assert len(saved) == len(names(run_dir / "clean")) == 8


def test_saving_nothing_at_all_raises_before_creating_anything(short_video, tmp_path):
    with (
        mock.patch("extract_memes.pipeline.download", side_effect=AssertionError("downloaded")),
        pytest.raises(ValueError, match="nothing would be saved"),
    ):
        run(str(short_video), runtime_dir=tmp_path, clean_method=None)

    assert list(tmp_path.iterdir()) == []


def test_unknown_clean_method_raises_before_creating_anything(short_video, tmp_path):
    with (
        mock.patch("extract_memes.pipeline.download", side_effect=AssertionError("downloaded")),
        pytest.raises(ValueError, match="trimmed_mean"),
    ):
        run(str(short_video), runtime_dir=tmp_path, clean_method="average")

    assert list(tmp_path.iterdir()) == []


def test_cleaned_image_differs_from_every_frame_it_was_made_from(short_video, tmp_path):
    saved = run(
        str(short_video), downloads_dir=tmp_path, runtime_dir=tmp_path, run_name="cleaned", save_high_res=True
    )

    cleaned = cv2.imread(str(saved[0]))
    batch_frames = [cv2.imread(str(path)) for path in sorted((tmp_path / "cleaned" / "high-res" / "meme_001").iterdir())]
    assert len(batch_frames) == 10
    assert all(not np.array_equal(cleaned, frame) for frame in batch_frames)
    # And it is less banded than the least banded frame it was made from.
    assert banding_score(cleaned) < min(banding_score(frame) for frame in batch_frames)


def test_save_frames_writes_every_sampled_frame(short_video, tmp_path):
    classifier = EveryNth(10)

    run(str(short_video), runtime_dir=tmp_path, fps=1.0, classifier=classifier, save_frames=True)

    # One file per sampled frame; the classifier is called more often, once per batch frame too.
    frames = names(tmp_path / "short" / "frames")
    assert len(frames) == 79
    assert all(MEME_NAME.match(name) for name in frames)
    assert frames[:2] == ["frame_000000_0.00s.jpg", "frame_000025_1.00s.jpg"]


def test_save_frames_does_not_change_what_the_classifier_sees(short_video, tmp_path):
    in_memory, on_disk = EveryNth(7), EveryNth(7)
    kwargs = dict(runtime_dir=tmp_path, fps=1.0)

    without = run(str(short_video), run_name="without", classifier=in_memory, **kwargs)
    with_frames = run(str(short_video), run_name="with", classifier=on_disk, save_frames=True, **kwargs)

    assert [path.name for path in without] == [path.name for path in with_frames]
    assert len(in_memory.frames) == len(on_disk.frames) > 79
    assert all(np.array_equal(a, b) for a, b in zip(in_memory.frames, on_disk.frames))


def test_classifier_reading_files_leaves_no_temporary_files(short_video, tmp_path, temp_root):
    complete, aborted = ReadsFiles(), ReadsFiles(fail_on_call=3)

    saved = run(str(short_video), runtime_dir=tmp_path, run_name="complete", fps=0.5, classifier=complete)
    with pytest.raises(RuntimeError, match="claude failed"):
        run(str(short_video), runtime_dir=tmp_path, run_name="aborted", fps=0.5, classifier=aborted)

    # `ReadsFiles` flags only its first call, which is a scan sample, so its one batch (51 frames
    # around 0.00s, at 25 fps) matches nothing and saves nothing.
    assert saved == []
    assert len(complete.paths) == 40 + 51
    assert len(aborted.paths) == 3
    assert all(path.parent.parent == temp_root for path in complete.paths + aborted.paths)
    assert list(temp_root.iterdir()) == []
    assert names(tmp_path / "complete") == ["clean"]
    assert names(tmp_path / "aborted") == ["clean"]
    # A batch that matches nothing is combined into nothing.
    assert names(tmp_path / "complete" / "clean") == []


def test_file_names_and_order(short_video, tmp_path):
    classifier = EveryNth(11)

    saved = run(
        str(short_video),
        runtime_dir=tmp_path,
        run_name="named",
        fps=2.0,
        classifier=classifier,
        save_low_res=True,
        save_high_res=True,
    )

    # At 2 fps on 25 fps video the step is 12 frames (0.48 s): calls 0, 11, 22, … are flagged.
    run_dir = tmp_path / "named"
    expected = [f"frame_{12 * call:06d}_{12 * call / 25:.2f}s.jpg" for call in range(0, 164, 11)]
    assert "frame_000264_10.56s.jpg" in expected
    # One scan-quality copy and one batch folder per scan hit, in the same order.
    assert names(run_dir / "low-res") == expected
    assert [path.name for path in batches(run_dir)] == [
        f"meme_{n:03d}" for n in range(1, len(expected) + 1)
    ]
    # One cleaned image per batch, returned in meme order.
    assert saved == [run_dir / "clean" / f"meme_{n:03d}.png" for n in range(1, len(expected) + 1)]
    # The batch frames keep the best file's own names, in video order within a batch.
    assert all(MEME_NAME.match(path.name) for batch in batches(run_dir) for path in batch.iterdir())


def test_save_low_res_writes_a_scan_quality_copy_of_each_meme(short_video, tmp_path):
    kwargs = dict(runtime_dir=tmp_path, fps=1.0, save_high_res=True)

    default = run(str(short_video), run_name="default", classifier=EveryNth(10), **kwargs)
    saved = run(str(short_video), run_name="low", classifier=EveryNth(10), save_low_res=True, **kwargs)

    assert [path.name for path in saved] == [path.name for path in default]
    assert all(path.parent == tmp_path / "low" / "clean" for path in saved)
    # One low-res copy per scan hit, so one per batch folder, at scan quality.
    low_res = sorted((tmp_path / "low" / "low-res").iterdir())
    assert len(low_res) == len(batches(tmp_path / "low"))
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
            save_timecodes=True,
        )

    assert saved == []
    assert capsys.readouterr().out == "No memes found.\n"
    assert [call.args[1] for call in download_spy.call_args_list] == ["worst"]
    # high-res/ always exists and low-res/ only when asked for; both stay empty.
    run_dir = tmp_path / ".runtime" / "short"
    expected = ["clean", "low-res"] if save_low_res else ["clean"]
    assert names(run_dir) == expected  # no timecodes.txt either, there is nothing to list
    assert all(names(folder) == [] for folder in run_dir.iterdir())


def test_proxy_is_forwarded_to_both_downloads(short_video, tmp_path):
    with mock.patch("extract_memes.pipeline.download", wraps=download) as download_spy:
        run(
            str(short_video),
            downloads_dir=tmp_path / "downloads",
            runtime_dir=tmp_path / ".runtime",
            classifier=EveryNth(10),
            proxy="socks5h://127.0.0.1:1080",
        )

    assert [call.kwargs["proxy"] for call in download_spy.call_args_list] == [
        "socks5h://127.0.0.1:1080",
        "socks5h://127.0.0.1:1080",
    ]


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


def test_progress_delta_reaches_the_bars_and_downloads(short_video, tmp_path):
    with (
        mock.patch("extract_memes.pipeline.tqdm", wraps=pipeline.tqdm) as progress,
        mock.patch("extract_memes.pipeline.download", wraps=pipeline.download) as downloads,
    ):
        run(
            str(short_video),
            runtime_dir=tmp_path,
            fps=0.5,
            classifier=EveryNth(10),
            progress_delta=3.0,
        )

    assert [call.kwargs["mininterval"] for call in progress.call_args_list] == [3.0, 3.0]
    assert [call.kwargs["progress_delta"] for call in downloads.call_args_list] == [3.0, 3.0]


def test_rerun_overwrites_and_keeps_other_files(short_video, tmp_path):
    kwargs = dict(runtime_dir=tmp_path, run_name="again", fps=0.5, save_high_res=True)
    run_dir = tmp_path / "again"
    first = run(str(short_video), classifier=EveryNth(10), save_low_res=True, **kwargs)
    first_low_res = names(run_dir / "low-res")
    first_batches = [path.name for path in batches(run_dir)]
    extra = run_dir / "high-res" / "keep-me.txt"
    extra.write_text("not written by the pipeline")
    # A folder left by a run made before the high-res/low-res layout.
    old = run_dir / "saved" / "thumb_frame_000000_0.00s.jpg"
    old.parent.mkdir()
    old.write_text("old layout")

    second = run(str(short_video), classifier=EveryNth(20), **kwargs)

    assert extra.is_file()
    assert all(path.is_file() for path in first)
    # The second run flags fewer memes, so it reuses the lower-numbered batch folders and leaves
    # the rest of the first run's batches in place. Batch numbers are per run, so `meme_002` now
    # holds a different meme; nothing from the first run is deleted.
    assert all(path.is_file() for path in second)
    assert [path.name for path in batches(run_dir)] == ["keep-me.txt", *first_batches]
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
    assert names(tmp_path / "broken") == ["clean"]
    assert names(tmp_path / "broken" / "clean") == []


def test_classifier_error_keeps_saved_frames_and_low_res_copies(short_video, tmp_path):
    classifier = mock.Mock(spec=FrameClassifier)
    classifier.is_meme_frame.side_effect = [True, False, RuntimeError("claude failed")]

    with pytest.raises(RuntimeError, match="claude failed"):
        run(
            str(short_video),
            runtime_dir=tmp_path,
            run_name="broken",
            fps=2.0,
            classifier=classifier,
            save_frames=True,
            save_low_res=True,
            save_high_res=True,
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
    saved = run(
        str(short_video),
        downloads_dir=tmp_path,
        runtime_dir=tmp_path,
        save_frames=save_frames,
        save_high_res=True,
    )

    # The three known cards, each as a batch of the 10 consecutive frames it's on screen for. The
    # one at 73 s falls between samples at 2 fps, so it needs the 3 fps default.
    run_dir = tmp_path / "short"
    assert [path.name for path in batches(run_dir)] == ["meme_001", "meme_002", "meme_003"]
    assert names(run_dir / "high-res" / "meme_001")[0] == "frame_000262_10.48s.jpg"
    assert names(run_dir / "high-res" / "meme_002")[0] == "frame_000716_28.64s.jpg"
    assert names(run_dir / "high-res" / "meme_003")[0] == "frame_001825_73.00s.jpg"
    assert [len(names(batch)) for batch in batches(run_dir)] == [10, 10, 10]
    assert "frame_000264_10.56s.jpg" in names(run_dir / "high-res" / "meme_001")
    assert "frame_000720_28.80s.jpg" in names(run_dir / "high-res" / "meme_002")
    assert "frame_001832_73.28s.jpg" in names(run_dir / "high-res" / "meme_003")
    assert all(path.is_file() for path in saved)
    assert (run_dir / "frames").is_dir() == save_frames


@pytest.mark.slow
def test_real_url_mock_classifier_run(tmp_path):
    downloads_dir = tmp_path / "downloads"

    saved = run(
        TEST_VIDEO_URL,
        downloads_dir=downloads_dir,
        runtime_dir=tmp_path / ".runtime",
        classifier=EveryNth(5),
        save_low_res=True,
        save_high_res=True,
    )

    run_dir = tmp_path / ".runtime" / "AElGyY97k_0"
    assert len(batches(run_dir)) == 6
    for path in saved:
        assert path.is_file()
        assert path.parent == run_dir / "clean"
        assert image_height(path) > image_height(sorted((run_dir / "low-res").iterdir())[0])
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
        save_high_res=True,
    )

    run_dir = tmp_path / ".runtime" / "AElGyY97k_0"
    assert len(batches(run_dir)) == 2
    for path in saved:
        assert path.is_file()
        assert path.parent == run_dir / "clean"
        assert image_height(path) > image_height(sorted((run_dir / "low-res").iterdir())[0])
    downloaded = [path.name for path in downloads_dir.rglob("*")]
    assert sorted(downloaded) == ["AElGyY97k_0_best.mp4", "AElGyY97k_0_worst.mp4"]
    assert not any("*" in name for name in downloaded)


def timecode_seconds(line: str) -> int:
    parts = [int(part) for part in line.split(" ")[0].split(":")]
    return sum(part * 60**power for power, part in enumerate(reversed(parts)))


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0.0, "0:00"),
        (7.9, "0:07"),
        (59.999, "0:59"),
        (60.0, "1:00"),
        (725.0, "12:05"),
        (3599.0, "59:59"),
        (3600.0, "1:00:00"),
        (7389.0, "2:03:09"),
        (-5.0, "0:00"),
    ],
)
def test_format_timecode(seconds, expected):
    assert format_timecode(seconds) == expected


def test_save_timecodes_lists_one_line_per_meme(short_video, tmp_path):
    kwargs = dict(runtime_dir=tmp_path, fps=1.0)

    saved = run(str(short_video), run_name="codes", classifier=EveryNth(10), save_timecodes=True, **kwargs)
    run(str(short_video), run_name="plain", classifier=EveryNth(10), **kwargs)

    lines = (tmp_path / "codes" / "timecodes.txt").read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(saved)
    assert all(TIMECODE_LINE.match(line) for line in lines)
    assert [line.split(" ", 1)[1] for line in lines] == [f"{MEME_LABEL} {n}" for n in range(1, len(saved) + 1)]
    times = [timecode_seconds(line) for line in lines]
    assert times == sorted(times)
    assert not (tmp_path / "plain" / "timecodes.txt").exists()


def test_timecodes_are_not_written_without_the_option(short_video, tmp_path):
    kwargs = dict(runtime_dir=tmp_path, run_name="keep", fps=1.0)
    run(str(short_video), classifier=EveryNth(10), save_timecodes=True, **kwargs)
    kept = (tmp_path / "keep" / "timecodes.txt").read_text(encoding="utf-8")

    run(str(short_video), classifier=EveryNth(10), **kwargs)

    assert (tmp_path / "keep" / "timecodes.txt").read_text(encoding="utf-8") == kept


def test_timecode_offset_shifts_every_line_and_clamps_at_zero(short_video, tmp_path):
    kwargs = dict(runtime_dir=tmp_path, fps=1.0, save_timecodes=True)

    run(str(short_video), run_name="at", classifier=EveryNth(10), **kwargs)
    run(str(short_video), run_name="before", classifier=EveryNth(10), timecode_offset=-1.0, **kwargs)

    at = (tmp_path / "at" / "timecodes.txt").read_text(encoding="utf-8").splitlines()
    before = (tmp_path / "before" / "timecodes.txt").read_text(encoding="utf-8").splitlines()
    assert len(before) == len(at)
    for at_line, before_line in zip(at, before, strict=True):
        assert at_line.split(" ", 1)[1] == before_line.split(" ", 1)[1]
        expected = max(0, timecode_seconds(at_line) - 1)
        assert timecode_seconds(before_line) == expected


def test_no_images_skips_the_best_quality_half(short_video, tmp_path, capsys):
    classifier = EveryNth(10)

    with mock.patch("extract_memes.pipeline.download", wraps=download) as download_spy:
        saved = run(
            str(short_video),
            downloads_dir=tmp_path / "downloads",
            runtime_dir=tmp_path,
            run_name="codes-only",
            fps=1.0,
            classifier=classifier,
            save_timecodes=True,
            no_images=True,
        )

    assert saved == []
    assert [call.args[1] for call in download_spy.call_args_list] == ["worst"]
    run_dir = tmp_path / "codes-only"
    assert names(run_dir) == ["timecodes.txt"]
    lines = (run_dir / "timecodes.txt").read_text(encoding="utf-8").splitlines()
    # One line per scan hit, not per confirmed batch, so every flagged frame is listed.
    flagged = sum(1 for index in range(len(classifier.frames)) if index % classifier.n == 0)
    assert len(lines) == flagged
    assert all(TIMECODE_LINE.match(line) for line in lines)
    assert [line.split(" ", 1)[1] for line in lines] == [f"{MEME_LABEL} {n}" for n in range(1, flagged + 1)]
    assert capsys.readouterr().out.endswith(f"Wrote {flagged} timecodes to {run_dir / 'timecodes.txt'}\n")


def test_no_images_keeps_the_scan_folders_and_the_offset(short_video, tmp_path):
    kwargs = dict(
        runtime_dir=tmp_path,
        fps=1.0,
        save_timecodes=True,
        save_frames=True,
        save_low_res=True,
        no_images=True,
    )

    run(str(short_video), run_name="at", classifier=EveryNth(10), **kwargs)
    run(str(short_video), run_name="before", classifier=EveryNth(10), timecode_offset=-1.0, **kwargs)

    assert names(tmp_path / "at") == ["frames", "low-res", "timecodes.txt"]
    at = (tmp_path / "at" / "timecodes.txt").read_text(encoding="utf-8").splitlines()
    before = (tmp_path / "before" / "timecodes.txt").read_text(encoding="utf-8").splitlines()
    for at_line, before_line in zip(at, before, strict=True):
        assert timecode_seconds(before_line) == max(0, timecode_seconds(at_line) - 1)


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"clean_method": None},
        {"save_high_res": True, "save_timecodes": True},
    ],
)
def test_no_images_without_anything_to_save_raises_before_creating_anything(short_video, tmp_path, kwargs):
    with pytest.raises(ValueError):
        run(str(short_video), runtime_dir=tmp_path, classifier=EveryNth(10), no_images=True, **kwargs)

    assert list(tmp_path.iterdir()) == []


def test_no_images_with_no_memes(short_video, tmp_path, capsys):
    saved = run(
        str(short_video),
        downloads_dir=tmp_path / "downloads",
        runtime_dir=tmp_path / ".runtime",
        classifier=NeverMeme(),
        save_timecodes=True,
        no_images=True,
    )

    assert saved == []
    assert capsys.readouterr().out == "No memes found.\n"
    assert not (tmp_path / ".runtime").exists()


def test_uploader_receives_the_saved_paths_and_source_once(short_video, tmp_path):
    uploader = FakeUploader()

    saved = run(
        str(short_video), runtime_dir=tmp_path, fps=1.0, classifier=EveryNth(10), uploader=uploader
    )

    assert uploader.calls == [(saved, str(short_video))]
    assert len(saved) > 0


def test_uploader_receives_batch_frames_when_clean_method_is_none(short_video, tmp_path):
    uploader = FakeUploader()

    saved = run(
        str(short_video),
        runtime_dir=tmp_path,
        fps=1.0,
        classifier=EveryNth(10),
        clean_method=None,
        save_high_res=True,
        uploader=uploader,
    )

    assert uploader.calls == [(saved, str(short_video))]
    assert len(saved) > 0


def test_no_uploader_means_nothing_is_uploaded(short_video, tmp_path):
    saved = run(str(short_video), runtime_dir=tmp_path, fps=1.0, classifier=EveryNth(10))

    assert len(saved) > 0  # sanity: the run did produce something to (not) upload


def test_a_failed_upload_does_not_abort_the_run(short_video, tmp_path, capsys):
    uploader = FakeUploader(error=RuntimeError("telegram rejected"))

    saved = run(
        str(short_video), runtime_dir=tmp_path, fps=1.0, classifier=EveryNth(10), uploader=uploader
    )

    assert uploader.calls == [(saved, str(short_video))]
    assert len(saved) > 0
    assert capsys.readouterr().out.endswith("Upload failed: telegram rejected\n")


def test_no_images_with_upload_to_telegram_raises_before_creating_anything(short_video, tmp_path):
    with pytest.raises(ValueError, match="nothing to upload"):
        run(
            str(short_video),
            runtime_dir=tmp_path,
            classifier=EveryNth(10),
            no_images=True,
            save_timecodes=True,
            upload_to="telegram",
            telegram_bot_token="tok",
            telegram_chat_id="123",
        )

    assert list(tmp_path.iterdir()) == []


def test_no_images_with_uploader_raises_before_creating_anything(short_video, tmp_path):
    with pytest.raises(ValueError, match="nothing to upload"):
        run(
            str(short_video),
            runtime_dir=tmp_path,
            classifier=EveryNth(10),
            no_images=True,
            save_timecodes=True,
            uploader=FakeUploader(),
        )

    assert list(tmp_path.iterdir()) == []


def test_upload_to_telegram_builds_a_telegram_uploader(short_video, tmp_path):
    with mock.patch("extract_memes.pipeline.TelegramUploader") as telegram_uploader:
        telegram_uploader.return_value = FakeUploader()
        run(
            str(short_video),
            runtime_dir=tmp_path,
            fps=1.0,
            classifier=EveryNth(10),
            upload_to="telegram",
            telegram_bot_token="tok",
            telegram_chat_id="123",
        )

    telegram_uploader.assert_called_once_with(bot_token="tok", chat_id="123")


def test_explicit_uploader_ignores_upload_to(short_video, tmp_path):
    uploader = FakeUploader()

    with mock.patch("extract_memes.pipeline.TelegramUploader") as telegram_uploader:
        run(
            str(short_video),
            runtime_dir=tmp_path,
            fps=1.0,
            classifier=EveryNth(10),
            uploader=uploader,
            upload_to="telegram",
        )

    telegram_uploader.assert_not_called()
    assert len(uploader.calls) == 1


def test_timecode_sender_receives_the_timecodes_and_source_once(short_video, tmp_path):
    sender = FakeTimecodeSender()

    saved = run(
        str(short_video),
        runtime_dir=tmp_path,
        fps=1.0,
        classifier=EveryNth(10),
        save_timecodes=True,
        timecode_sender=sender,
    )

    written = (tmp_path / default_run_name(str(short_video)) / "timecodes.txt").read_text(
        encoding="utf-8"
    ).splitlines()
    assert sender.calls == [(written, str(short_video))]
    assert len(saved) > 0


def test_no_timecode_sender_means_nothing_is_sent(short_video, tmp_path):
    saved = run(str(short_video), runtime_dir=tmp_path, fps=1.0, classifier=EveryNth(10))

    assert len(saved) > 0  # sanity: the run did produce something to (not) send


def test_a_failed_timecode_send_does_not_abort_the_run(short_video, tmp_path, capsys):
    sender = FakeTimecodeSender(error=RuntimeError("telegram rejected"))

    saved = run(
        str(short_video),
        runtime_dir=tmp_path,
        fps=1.0,
        classifier=EveryNth(10),
        timecode_sender=sender,
    )

    assert len(sender.calls) == 1
    assert len(saved) > 0
    assert capsys.readouterr().out.endswith("Timecode send failed: telegram rejected\n")


def test_no_images_with_timecode_sender_sends_the_scan_based_list(short_video, tmp_path):
    sender = FakeTimecodeSender()

    saved = run(
        str(short_video),
        runtime_dir=tmp_path,
        fps=1.0,
        classifier=EveryNth(10),
        no_images=True,
        timecode_sender=sender,
    )

    assert saved == []
    assert len(sender.calls) == 1
    timecodes, source = sender.calls[0]
    assert source == str(short_video)
    assert all(TIMECODE_LINE.match(line) for line in timecodes)


def test_no_images_with_send_timecodes_to_alone_does_not_raise(short_video, tmp_path):
    saved = run(
        str(short_video),
        runtime_dir=tmp_path,
        classifier=EveryNth(10),
        no_images=True,
        send_timecodes_to="telegram",
        telegram_bot_token="tok",
        timecode_chat_id="123",
    )

    assert saved == []


def test_no_images_with_uploader_still_raises_regardless_of_timecode_sender(short_video, tmp_path):
    with pytest.raises(ValueError, match="nothing to upload"):
        run(
            str(short_video),
            runtime_dir=tmp_path,
            classifier=EveryNth(10),
            no_images=True,
            uploader=FakeUploader(),
            timecode_sender=FakeTimecodeSender(),
        )

    assert list(tmp_path.iterdir()) == []


def test_send_timecodes_to_telegram_builds_a_telegram_timecode_sender(short_video, tmp_path):
    with mock.patch("extract_memes.pipeline.TelegramTimecodeSender") as telegram_sender:
        telegram_sender.return_value = FakeTimecodeSender()
        run(
            str(short_video),
            runtime_dir=tmp_path,
            fps=1.0,
            classifier=EveryNth(10),
            send_timecodes_to="telegram",
            telegram_bot_token="tok",
            timecode_chat_id="123",
        )

    telegram_sender.assert_called_once_with(bot_token="tok", chat_id="123")


def test_explicit_timecode_sender_ignores_send_timecodes_to(short_video, tmp_path):
    sender = FakeTimecodeSender()

    with mock.patch("extract_memes.pipeline.TelegramTimecodeSender") as telegram_sender:
        run(
            str(short_video),
            runtime_dir=tmp_path,
            fps=1.0,
            classifier=EveryNth(10),
            timecode_sender=sender,
            send_timecodes_to="telegram",
        )

    telegram_sender.assert_not_called()
    assert len(sender.calls) == 1


def test_uploader_receives_the_fetched_source_info(short_video, tmp_path):
    info = SourceInfo(title="A title", thumbnail_url="https://img/t.jpg")
    uploader = FakeUploader()

    with mock.patch("extract_memes.pipeline.fetch_source_info", return_value=info) as fetch:
        run(str(short_video), runtime_dir=tmp_path, fps=1.0, classifier=EveryNth(10), uploader=uploader, proxy="p")

    fetch.assert_called_once_with(str(short_video), proxy="p")
    assert uploader.infos == [info]


def test_a_local_file_source_has_no_info(short_video, tmp_path):
    uploader = FakeUploader()

    run(str(short_video), runtime_dir=tmp_path, fps=1.0, classifier=EveryNth(10), uploader=uploader)

    assert uploader.infos == [None]


def test_a_failed_info_fetch_still_uploads_without_info(short_video, tmp_path, capsys):
    uploader = FakeUploader()

    with mock.patch("extract_memes.pipeline.fetch_source_info", side_effect=RuntimeError("blocked")):
        run(str(short_video), runtime_dir=tmp_path, fps=1.0, classifier=EveryNth(10), uploader=uploader)

    assert uploader.infos == [None]
    assert "Could not fetch the video's title and thumbnail: blocked" in capsys.readouterr().out


def scan_call_count(video: Path, fps: float = 2.0) -> int:
    return sum(1 for _ in sample_frames(video, fps=fps))


# At 2 fps on 25 fps video the scan samples every 0.48 s, so calls 0-2 are at 0, 0.48 and 0.96 s.
CLOSE_RUNS = {0, 1, 2, 3, 10, 11}


def timecode_lines(run_dir: Path) -> list[str]:
    return (run_dir / "timecodes.txt").read_text(encoding="utf-8").splitlines()


def test_flagged_frames_within_the_merge_window_are_one_meme(short_video, tmp_path):
    # Flagged at 0, 0.48, 0.96 | 1.44 | 4.8, 5.28 s: the 1.44 s frame is 1.44 s from the first.
    run(
        str(short_video),
        runtime_dir=tmp_path,
        fps=2.0,
        run_name="merged",
        classifier=FlagsScanCalls(CLOSE_RUNS, scan_call_count(short_video)),
        save_low_res=True,
        save_timecodes=True,
        no_images=True,
    )

    run_dir = tmp_path / "merged"
    assert len(names(run_dir / "low-res")) == len(CLOSE_RUNS)
    assert [line.split(" ", 1)[0] for line in timecode_lines(run_dir)] == ["0:00", "0:01", "0:04"]
    assert [line.split(" ", 1)[1] for line in timecode_lines(run_dir)] == [
        f"{MEME_LABEL} {n}" for n in (1, 2, 3)
    ]


def test_merge_window_is_measured_from_the_first_flagged_frame(short_video, tmp_path):
    # Every call 0-5 is flagged, spanning 0-2.4 s; a window of 1 s covers calls 0-2, 1.44 s starts the next.
    run(
        str(short_video),
        runtime_dir=tmp_path,
        fps=2.0,
        classifier=FlagsScanCalls(set(range(6)), scan_call_count(short_video)),
        save_timecodes=True,
        no_images=True,
    )

    assert [line.split(" ", 1)[0] for line in timecode_lines(tmp_path / "short")] == ["0:00", "0:01"]


def test_merge_window_boundary_is_inclusive(short_video, tmp_path):
    kwargs = dict(runtime_dir=tmp_path, fps=2.0, save_timecodes=True, no_images=True)
    classifier = lambda: FlagsScanCalls({0, 2}, scan_call_count(short_video))  # noqa: E731

    run(str(short_video), run_name="equal", classifier=classifier(), merge_window=0.96, **kwargs)
    run(str(short_video), run_name="below", classifier=classifier(), merge_window=0.95, **kwargs)

    assert len(timecode_lines(tmp_path / "equal")) == 1
    assert len(timecode_lines(tmp_path / "below")) == 2


def test_merge_window_zero_merges_nothing(short_video, tmp_path):
    run(
        str(short_video),
        runtime_dir=tmp_path,
        fps=2.0,
        classifier=FlagsScanCalls(CLOSE_RUNS, scan_call_count(short_video)),
        merge_window=0,
        save_timecodes=True,
        no_images=True,
    )

    assert len(timecode_lines(tmp_path / "short")) == len(CLOSE_RUNS)


def test_a_merged_meme_is_extracted_once_over_the_extended_window(short_video, tmp_path):
    # Scan hits at 4.8 and 5.28 s: one meme whose window runs 3.8 s to 6.28 s, 62 frames at 25 fps, plus one.
    classifier = FlagsScanCalls({10, 11}, scan_call_count(short_video))
    saved = run(
        str(short_video),
        runtime_dir=tmp_path,
        fps=2.0,
        run_name="merged",
        classifier=classifier,
        save_high_res=True,
    )

    run_dir = tmp_path / "merged"
    assert [path.name for path in batches(run_dir)] == ["meme_001"]
    assert saved == [run_dir / "clean" / "meme_001.png"]
    assert len(names(run_dir / "high-res" / "meme_001")) == 63
    assert classifier.calls == classifier.scan_calls + 63


def test_unmerged_hits_are_extracted_separately(short_video, tmp_path):
    run(
        str(short_video),
        runtime_dir=tmp_path,
        fps=2.0,
        run_name="split",
        classifier=FlagsScanCalls({10, 11}, scan_call_count(short_video)),
        merge_window=0,
        save_high_res=True,
    )

    run_dir = tmp_path / "split"
    assert [path.name for path in batches(run_dir)] == ["meme_001", "meme_002"]
    assert len(names(run_dir / "high-res" / "meme_001")) == 51
    assert len(names(run_dir / "high-res" / "meme_002")) == 51


def test_merged_memes_are_uploaded_and_sent_once(short_video, tmp_path):
    uploader = FakeUploader()
    sender = FakeTimecodeSender()

    saved = run(
        str(short_video),
        runtime_dir=tmp_path,
        fps=2.0,
        classifier=FlagsScanCalls({10, 11}, scan_call_count(short_video)),
        uploader=uploader,
        timecode_sender=sender,
    )

    assert len(saved) == 1
    assert uploader.calls[0][0] == saved
    assert len(sender.calls[0][0]) == 1


def test_negative_merge_window_raises_before_creating_anything(short_video, tmp_path):
    with pytest.raises(ValueError, match="merge_window"):
        run(str(short_video), runtime_dir=tmp_path, fps=2.0, classifier=EveryNth(10), merge_window=-0.1)

    assert list(tmp_path.iterdir()) == []
