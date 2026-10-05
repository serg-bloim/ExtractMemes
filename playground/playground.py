"""Manual pipeline experiments to run one at a time from the IDE.

The functions are named `test_*` only so IDE pytest integrations show a run icon next to each one.
They are not tests: they assert nothing. The runs use the pipeline's default heuristic classifier
unless they say otherwise; `test_custom_model_and_effort` and `test_classify_one_frame` call the
real Claude classifier (slow, and costs usage). A bare `pytest` from the
project root collects nothing from here (`testpaths` in pyproject.toml is `tests`).

Output goes under `.runtime/_playground/<run_name>/`, with downloads in
`.runtime/_playground/downloads/`. Paths are resolved from this file's location, not the cwd.

`python playground/playground.py` runs `test_progress_bars_demo()`, which uses no Claude usage.
"""

import time
from pathlib import Path

import cv2

import numpy as np

from extract_memes.batch_cleaner import METHODS, banding_score, combine
from extract_memes.classifier import ClaudeCliClassifier, FrameClassifier
from extract_memes.frame_extractor import frame_at, frames_from
from extract_memes.heuristic_classifier import HeuristicClassifier
from extract_memes.pipeline import _to_scan_size, run

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SHORT_VIDEO = PROJECT_ROOT / "sample" / "short.mp4"
FULL_VIDEO = PROJECT_ROOT / "sample" / "full.mp4"
PLAYGROUND_DIR = PROJECT_ROOT / ".runtime" / "_playground"
DOWNLOADS_DIR = PLAYGROUND_DIR / "downloads"
LABELED_DATASET = PROJECT_ROOT / "data" / "labeled_dataset"
CLEAN_DIR = PLAYGROUND_DIR / "clean"
# The 1080p download of the source of sample/full.mp4, and timestamps of cards it contains.
REAL_VIDEO = PROJECT_ROOT / ".runtime" / "downloads" / "0TSqnhLXYfA_best.mp4"
REAL_CARD_TIMES = (5.76, 99.56, 687.36, 2717.76, 2812.32)
FULL_VIDEO_URL = "https://www.youtube.com/watch?v=Ij427pW96aI"


class SlowEveryNthClassifier(FrameClassifier):
    """Flags calls 0, n, 2n, …, sleeping on every call so the progress bars have something to show."""

    def __init__(self, n: int, delay: float) -> None:
        self.n = n
        self.delay = delay
        self.calls = 0

    def is_meme(self, image_path: Path) -> bool:
        time.sleep(self.delay)
        flagged = self.calls % self.n == 0
        self.calls += 1
        return flagged


def _run(source: Path, run_name: str, **kwargs) -> None:
    saved = run(
        str(source),
        downloads_dir=DOWNLOADS_DIR,
        runtime_dir=PLAYGROUND_DIR,
        run_name=run_name,
        **kwargs,
    )
    print(f"Saved {len(saved)} memes to {PLAYGROUND_DIR / run_name / 'high-res'}:")
    for path in saved:
        print(f"  {path}")


def test_default_run():
    _run(SHORT_VIDEO, "default_run")


def test_custom_model_and_effort():
    _run(
        SHORT_VIDEO,
        "custom_model_effort",
        classifier_model="claude-sonnet-5",
        classifier_effort="high",
        classifier_type="claude",
    )


def test_different_fps():
    _run(SHORT_VIDEO, "fps_0_5", fps=0.5)


def test_full_video_run():
    _run(FULL_VIDEO, "full_video", fps=0.5)


def test_classify_one_frame():
    image_path = PLAYGROUND_DIR / "single_frame.jpg"
    PLAYGROUND_DIR.mkdir(parents=True, exist_ok=True)
    # A known glitch-framed meme card.
    cv2.imwrite(str(image_path), frame_at(SHORT_VIDEO, 10.56))
    print(f"Saved {image_path}")
    print("YES" if ClaudeCliClassifier().is_meme(image_path) else "NO")


def test_progress_bars_demo():
    _run(
        SHORT_VIDEO,
        "progress_bars_demo",
        fps=2.0,
        classifier=SlowEveryNthClassifier(n=5, delay=0.1),
    )


def test_score_labeled_set():
    classifier = HeuristicClassifier()
    correct = total = 0
    for label, expected in [("positive", True), ("negative", False)]:
        for image_path in sorted((LABELED_DATASET / label).glob("*.png")):
            verdict = classifier.is_meme(image_path)
            scores = classifier.scores(cv2.imread(str(image_path)))
            total += 1
            correct += verdict == expected
            wrong = "" if verdict == expected else "  <-- WRONG"
            print(
                f"{label:8} {image_path.name:24} band={scores.band:5.1f} "
                f"texture={scores.texture:4.1f} {'meme' if verdict else 'not meme'}{wrong}"
            )
    print(f"{correct}/{total} correct")


def _batch_at(video: Path, timestamp: float, window: float = 1.0) -> list:
    """The frames the pipeline would keep for a meme at `timestamp`: flagged, full quality."""
    classifier = HeuristicClassifier()
    start = max(0.0, timestamp - window)
    count = round(2 * window * 25) + 1
    return [
        frame
        for _, _, frame in frames_from(video, start, count)
        if classifier.is_meme_frame(_to_scan_size(frame, (144, 256)))
    ]


def _label_panel(image, text: str):
    """One contact-sheet panel: the image with a caption strip above it."""
    panel = cv2.copyMakeBorder(image, 34, 0, 0, 0, cv2.BORDER_CONSTANT, value=(20, 20, 20))
    cv2.putText(panel, text, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return panel


def _sheet(panels: list, columns: int = 3):
    """Lay labelled panels out in a grid, padding the last row so it can be stacked."""
    blank = np.zeros_like(panels[0])
    rows = [panels[i : i + columns] for i in range(0, len(panels), columns)]
    rows[-1] += [blank] * (columns - len(rows[-1]))
    return np.vstack([np.hstack(row) for row in rows])


def _compare_methods(video: Path, timestamp: float, label: str) -> None:
    """Write one image per cleaning method for one meme batch, plus a sheet and a 100% crop."""
    if not video.is_file():
        print(f"{video} is absent; skipping.")
        return
    frames = _batch_at(video, timestamp)
    if not frames:
        print(f"No meme frames around {timestamp}s in {video.name}; skipping.")
        return

    out_dir = CLEAN_DIR / label
    (out_dir / "inputs").mkdir(parents=True, exist_ok=True)
    for index, frame in enumerate(frames):
        cv2.imwrite(str(out_dir / "inputs" / f"frame_{index:02d}.png"), frame)

    height, width = frames[0].shape[:2]
    crop = np.s_[height // 2 - 180 : height // 2 + 180, width // 2 - 240 : width // 2 + 240]
    reference = combine(frames, "trimmed_mean")
    panels, details = [], []
    print(f"\n{label}: {len(frames)} frames, {width}x{height}")
    print(f"{'method':14} {'ms':>6} {'banding':>8} {'vs trimmed_mean':>16}")
    for number, method in enumerate(METHODS, start=1):
        started = time.perf_counter()
        cleaned = combine(frames, method)
        elapsed = (time.perf_counter() - started) * 1000
        cv2.imwrite(str(out_dir / f"{number:02d}_{method}.png"), cleaned)
        panels.append(_label_panel(cv2.resize(cleaned, (640, round(640 * height / width))), method))
        details.append(_label_panel(cleaned[crop], method))
        difference = np.abs(cleaned.astype(np.float32) - reference).mean()
        print(f"{method:14} {elapsed:6.0f} {banding_score(cleaned):8.2f} {difference:16.1f}")
    worst, best = max(frames, key=banding_score), min(frames, key=banding_score)
    print(f"{'input frames':14} {'':>6} {banding_score(best):8.2f} (best) {banding_score(worst):.2f} (worst)")

    cv2.imwrite(str(out_dir / "sheet.png"), _sheet(panels))
    cv2.imwrite(str(out_dir / "detail.png"), _sheet(details))
    print(f"Wrote {out_dir}")


def test_full_video_every_method():
    """Extract every meme of the real video, then clean each batch with every method.

    Writes `.runtime/full_experiment/high-res/meme_<n>/` (the batches) and
    `.runtime/full_experiment/clean/meme_<n>/<method>.png` (one cleaned image per method), so the
    methods can be compared on all ~93 memes. Downloads are reused from `.runtime/downloads/`.
    """
    run_dir = PROJECT_ROOT / ".runtime" / "full_experiment"
    saved = run(
        FULL_VIDEO_URL,
        downloads_dir=PROJECT_ROOT / ".runtime" / "downloads",
        runtime_dir=run_dir.parent,
        run_name=run_dir.name,
        clean_method=None,
        save_high_res=True,
        save_frames=True,
        save_low_res=True,
    )
    print(f"{len(saved)} frames in {len(list((run_dir / 'high-res').iterdir()))} batches")
    _clean_every_method(run_dir)


def _clean_every_method(run_dir: Path) -> None:
    """Clean every batch of a finished run with every method, into `clean/meme_<n>/<method>.png`."""
    for meme_dir in sorted((run_dir / "high-res").iterdir()):
        frames = [cv2.imread(str(path)) for path in sorted(meme_dir.iterdir())]
        if not frames:
            print(f"{meme_dir.name}: empty, skipped")
            continue
        out_dir = run_dir / "clean" / meme_dir.name
        out_dir.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        for method in METHODS:
            cv2.imwrite(str(out_dir / f"{method}.png"), combine(frames, method))
        print(f"{meme_dir.name}: {len(frames)} frames, {len(METHODS)} methods, {time.perf_counter() - started:.1f}s")


def test_compare_cleaners_on_real_batch():
    for timestamp in REAL_CARD_TIMES:
        _compare_methods(REAL_VIDEO, timestamp, f"real_{timestamp:.0f}s")


def test_compare_cleaners_on_short_video():
    _compare_methods(SHORT_VIDEO, 10.56, "short_10s")


if __name__ == "__main__":
    test_full_video_run()
