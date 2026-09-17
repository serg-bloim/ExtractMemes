"""Manual pipeline experiments to run one at a time from the IDE.

The functions are named `test_*` only so IDE pytest integrations show a run icon next to each one.
They are not tests: they assert nothing. The runs use the pipeline's default heuristic classifier
unless they say otherwise; `test_custom_model_and_effort` and `test_classify_one_frame` call the
real Claude classifier (slow, and costs usage). This file's name doesn't match pytest's
`test_*.py` / `*_test.py` collection patterns, so running `pytest` from the project root collects
nothing from here.

Output goes under `.runtime/_playground/<run_name>/`, with downloads in
`.runtime/_playground/downloads/`. Paths are resolved from this file's location, not the cwd.

`python playground/playground.py` runs `test_progress_bars_demo()`, which uses no Claude usage.
"""

import time
from pathlib import Path

import cv2

from extract_memes.classifier import ClaudeCliClassifier, FrameClassifier
from extract_memes.frame_extractor import frame_at
from extract_memes.heuristic_classifier import HeuristicClassifier
from extract_memes.pipeline import run

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SHORT_VIDEO = PROJECT_ROOT / "sample" / "short.mp4"
FULL_VIDEO = PROJECT_ROOT / "sample" / "full.mp4"
PLAYGROUND_DIR = PROJECT_ROOT / ".runtime" / "_playground"
DOWNLOADS_DIR = PLAYGROUND_DIR / "downloads"
LABELED_DATASET = PROJECT_ROOT / "data" / "labeled_dataset"


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


if __name__ == "__main__":
    test_progress_bars_demo()
