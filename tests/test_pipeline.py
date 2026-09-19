import re
from pathlib import Path
from unittest import mock

import cv2
import numpy as np
import pytest

from extract_memes import pipeline
from extract_memes.batch_cleaner import banding_score
from extract_memes.classifier import FrameClassifier
from extract_memes.downloader import download, download_sections
from extract_memes.pipeline import (
    MEME_LABEL,
    _extraction_sources,
    default_run_name,
    format_timecode,
    run,
    section_ranges,
)
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

    def upload_all(self, image_paths: list[Path], source: str) -> None:
        self.calls.append((list(image_paths), source))
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

    # The two known cards, each as a batch of the 10 consecutive frames it's on screen for.
    run_dir = tmp_path / "short"
    assert [path.name for path in batches(run_dir)] == ["meme_001", "meme_002"]
    assert names(run_dir / "high-res" / "meme_001")[0] == "frame_000262_10.48s.jpg"
    assert names(run_dir / "high-res" / "meme_002")[0] == "frame_000716_28.64s.jpg"
    assert [len(names(batch)) for batch in batches(run_dir)] == [10, 10]
    assert "frame_000264_10.56s.jpg" in names(run_dir / "high-res" / "meme_001")
    assert "frame_000720_28.80s.jpg" in names(run_dir / "high-res" / "meme_002")
    assert all(path.is_file() for path in saved)
    assert (run_dir / "frames").is_dir() == save_frames


@pytest.mark.parametrize(
    ("timestamps", "expected"),
    [
        ([10.0], [(8, 12)]),
        ([0.2], [(0, 3)]),  # clamped at the start, so the window reaches further right
        ([10.0, 10.5], [(8, 12)]),  # overlapping windows
        ([10.0, 20.0], [(8, 22)]),  # a gap small enough to bridge
        ([10.0, 40.0], [(8, 12), (38, 42)]),
        ([40.0, 10.0], [(8, 12), (38, 42)]),  # out of order
    ],
)
def test_section_ranges(timestamps, expected):
    assert section_ranges(timestamps, window_seconds=1.0) == expected


def test_section_ranges_respects_the_window_and_gap():
    assert section_ranges([10.0, 25.0], window_seconds=3.0, pad=1.0, gap=2.0) == [(6, 14), (21, 29)]
    assert section_ranges([10.0, 25.0], window_seconds=3.0, pad=1.0, gap=8.0) == [(6, 29)]


def extraction_sources(short_video, tmp_path, timestamps, **kwargs):
    """Call `_extraction_sources` with `short_video` as the already-downloaded scan copy."""
    return _extraction_sources(
        kwargs.pop("source", TEST_VIDEO_URL),
        timestamps,
        tmp_path / "downloads",
        kwargs.pop("window_seconds", 1.0),
        short_video,
        kwargs.pop("proxy", None),
        kwargs.pop("full_download", False),
    )


def test_a_url_source_downloads_only_the_meme_windows(short_video, tmp_path):
    sections = [(Path("/fake/a.mp4"), 8.0), (Path("/fake/b.mp4"), 27.0)]

    with (
        mock.patch("extract_memes.pipeline.download_sections", return_value=sections) as partial,
        mock.patch("extract_memes.pipeline.download", side_effect=AssertionError("whole file")),
    ):
        sources = extraction_sources(short_video, tmp_path, [10.48, 28.64], proxy="socks5h://p:1")

    partial.assert_called_once_with(
        TEST_VIDEO_URL, [(8, 12), (27, 31)], tmp_path / "downloads", proxy="socks5h://p:1"
    )
    # Each timestamp reads from the section covering it, offset by where that section starts.
    assert sources == sections


def test_two_memes_in_one_section_share_its_file(short_video, tmp_path):
    sections = [(Path("/fake/a.mp4"), 8.0)]

    with mock.patch("extract_memes.pipeline.download_sections", return_value=sections) as partial:
        sources = extraction_sources(short_video, tmp_path, [10.0, 11.0])

    assert partial.call_args.args[1] == [(8, 13)]
    assert sources == [(Path("/fake/a.mp4"), 8.0), (Path("/fake/a.mp4"), 8.0)]


@pytest.mark.parametrize("kwargs", [{"full_download": True}, {"source": "LOCAL"}])
def test_the_whole_file_is_downloaded_on_request_and_for_a_local_file(
    short_video, tmp_path, kwargs
):
    if kwargs.get("source") == "LOCAL":
        kwargs["source"] = str(short_video)

    with (
        mock.patch("extract_memes.pipeline.download", return_value=Path("/fake/best.mp4")) as whole,
        mock.patch(
            "extract_memes.pipeline.download_sections", side_effect=AssertionError("sections")
        ),
    ):
        sources = extraction_sources(short_video, tmp_path, [10.0, 40.0], **kwargs)

    whole.assert_called_once()
    assert sources == [(Path("/fake/best.mp4"), 0.0)] * 2


def test_dense_memes_fall_back_to_the_whole_file(short_video, tmp_path, capsys):
    # short.mp4 runs 78.56s; these windows merge into one range covering nearly all of it.
    timestamps = [float(second) for second in range(2, 70, 5)]

    with (
        mock.patch("extract_memes.pipeline.download", return_value=Path("/fake/best.mp4")) as whole,
        mock.patch(
            "extract_memes.pipeline.download_sections", side_effect=AssertionError("sections")
        ),
    ):
        sources = extraction_sources(short_video, tmp_path, timestamps)

    whole.assert_called_once()
    assert sources == [(Path("/fake/best.mp4"), 0.0)] * len(timestamps)
    assert "downloading the whole video instead" in capsys.readouterr().out


def test_a_failed_section_download_falls_back_to_the_whole_file(short_video, tmp_path, capsys):
    with (
        mock.patch("extract_memes.pipeline.download", return_value=Path("/fake/best.mp4")) as whole,
        mock.patch(
            "extract_memes.pipeline.download_sections",
            side_effect=RuntimeError("Requested format is not available"),
        ),
    ):
        sources = extraction_sources(short_video, tmp_path, [10.0])

    whole.assert_called_once()
    assert sources == [(Path("/fake/best.mp4"), 0.0)]
    output = capsys.readouterr().out
    assert "Requested format is not available" in output
    assert "downloading the whole video instead" in output


def test_missing_sections_fall_back_to_the_whole_file(short_video, tmp_path, capsys):
    with (
        mock.patch("extract_memes.pipeline.download", return_value=Path("/fake/best.mp4")) as whole,
        mock.patch("extract_memes.pipeline.download_sections", return_value=[]),
    ):
        sources = extraction_sources(short_video, tmp_path, [10.0, 40.0])

    whole.assert_called_once()
    assert sources == [(Path("/fake/best.mp4"), 0.0)] * 2
    assert "asked for 2 sections, got 0" in capsys.readouterr().out


def cut(source: Path, dest: Path, start: float, end: float) -> Path:
    """Write `source`'s frames between `start` and `end` to `dest`, as a section download would.

    The result begins exactly at `start`, which is the property `force_keyframes_at_cuts` buys from
    ffmpeg and the reason the pipeline can map a position in a section back to the whole video.
    """
    capture = cv2.VideoCapture(str(source))
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        size = (
            int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )
        writer = cv2.VideoWriter(str(dest), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
        try:
            capture.set(cv2.CAP_PROP_POS_FRAMES, round(start * fps))
            for _ in range(round((end - start) * fps)):
                ok, frame = capture.read()
                if not ok:
                    break
                writer.write(frame)
        finally:
            writer.release()
    finally:
        capture.release()
    return dest


def test_a_section_run_produces_the_same_output_as_a_whole_file_run(short_video, tmp_path):
    """The point of the whole feature: identical frames, names and timecodes, fewer bytes."""

    def sections(source, ranges, dest_dir, proxy=None):
        dest_dir.mkdir(parents=True, exist_ok=True)
        return [
            (cut(short_video, dest_dir / f"section_{start}-{end}.mp4", start, end), float(start))
            for start, end in ranges
        ]

    def outputs(run_dir: Path) -> tuple[list[str], str]:
        frames = sorted(str(path.relative_to(run_dir)) for path in (run_dir / "high-res").rglob("*"))
        return frames, (run_dir / "timecodes.txt").read_text(encoding="utf-8")

    whole_run = tmp_path / "whole"
    section_run = tmp_path / "sections"
    common = dict(save_high_res=True, save_timecodes=True, downloads_dir=tmp_path / "downloads")
    # Sparse enough that the windows stay well under the coverage guard: three memes, one of them
    # clamped at the start of the video and one running up against its end.
    run(str(short_video), runtime_dir=whole_run, classifier=EveryNth(80), **common)
    with (
        mock.patch("extract_memes.pipeline.download", return_value=short_video),
        mock.patch("extract_memes.pipeline.download_sections", side_effect=sections) as partial,
    ):
        run(TEST_VIDEO_URL, runtime_dir=section_run, classifier=EveryNth(80), **common)

    assert partial.call_args.args[1] == [(0, 3), (36, 40), (75, 79)]
    assert outputs(section_run / "AElGyY97k_0") == outputs(whole_run / "short")


class OneMeme(FrameClassifier):
    """Flags the first scan frame, then every frame once `extracting` is set.

    One meme, early in the video, with a full batch behind it — so a run stays well under the
    coverage guard and still produces something to compare.
    """

    def __init__(self) -> None:
        self.extracting = False
        self.count = 0

    def is_meme_frame(self, frame: np.ndarray) -> bool:
        self.count += 1
        return self.extracting or self.count == 1

    def is_meme(self, image_path: Path) -> bool:
        raise AssertionError("the pipeline must classify frames in memory, not files")


@pytest.mark.slow
def test_real_url_partial_download_run(tmp_path):
    downloads_dir = tmp_path / "downloads"

    def one_meme_run(run_name, **kwargs):
        """Run the pipeline, flipping the classifier over once the extraction copy is fetched."""
        classifier = OneMeme()

        def sections(*args, **call_kwargs):
            fetched = download_sections(*args, **call_kwargs)
            classifier.extracting = True
            return fetched

        def whole(source, quality, *args, **call_kwargs):
            fetched = download(source, quality, *args, **call_kwargs)
            classifier.extracting |= quality == "best"
            return fetched

        with (
            mock.patch("extract_memes.pipeline.download_sections", side_effect=sections) as partial,
            mock.patch("extract_memes.pipeline.download", side_effect=whole),
        ):
            saved = run(
                TEST_VIDEO_URL,
                downloads_dir=downloads_dir,
                runtime_dir=tmp_path / run_name,
                classifier=classifier,
                save_timecodes=True,
                save_high_res=True,
                **kwargs,
            )
        return saved, partial.call_count

    saved, section_downloads = one_meme_run("partial")
    whole_saved, whole_section_downloads = one_meme_run("whole", full_download=True)

    assert (section_downloads, whole_section_downloads) == (1, 0)
    downloaded = sorted(path.name for path in downloads_dir.rglob("*"))
    assert downloaded == [
        "AElGyY97k_0_best.mp4",
        "AElGyY97k_0_best_0-3.mp4",
        "AElGyY97k_0_worst.mp4",
    ]
    section = downloads_dir / "AElGyY97k_0_best_0-3.mp4"
    assert section.stat().st_size < (downloads_dir / "AElGyY97k_0_best.mp4").stat().st_size
    # Same memes, same frame names, same timecodes -- only the bytes fetched differ.
    assert [path.name for path in saved] == [path.name for path in whole_saved] != []
    outputs = [
        (
            sorted(path.name for path in (tmp_path / name / "AElGyY97k_0" / "high-res").rglob("*")),
            (tmp_path / name / "AElGyY97k_0" / "timecodes.txt").read_text(encoding="utf-8"),
        )
        for name in ("partial", "whole")
    ]
    assert outputs[0] == outputs[1]
    assert outputs[0][1].strip() != ""


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
        full_download=True,
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
        full_download=True,
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
