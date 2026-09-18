"""Developer runner: push a real YouTube URL through the full pipeline.

Uses the real Claude classifier by default. `--mock-type every-n` or `--mock-type random` swaps in
a free fake classifier to check downloads and wiring without Claude usage. Downloads go to
`.runtime/downloads/` and run artifacts to `.runtime/<run-name>/`, relative to the cwd.
"""

import argparse
import random
from pathlib import Path

from extract_memes.classifier import ClaudeCliClassifier, FrameClassifier
from extract_memes.pipeline import run

DEFAULT_URL = "https://youtu.be/AElGyY97k_0"


class EveryNthClassifier(FrameClassifier):
    """Flags calls 0, n, 2n, …, so the first sampled frame is always flagged."""

    def __init__(self, n: int) -> None:
        self.n = n
        self.calls = 0

    def is_meme(self, image_path: Path) -> bool:
        flagged = self.calls % self.n == 0
        self.calls += 1
        return flagged


class RandomClassifier(FrameClassifier):
    """Flags each frame independently with the given probability."""

    def __init__(self, probability: float) -> None:
        self.probability = probability

    def is_meme(self, image_path: Path) -> bool:
        return random.random() < self.probability


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url", nargs="?", default=DEFAULT_URL, help="default: %(default)s")
    parser.add_argument("--fps", type=float, default=2.0, help="default: %(default)s")
    parser.add_argument(
        "--mock-type",
        choices=["every-n", "random", "claude"],
        help="fake classifier to use (default: the real Claude classifier, same as 'claude')",
    )
    parser.add_argument("--every-n", type=int, default=5, help="default: %(default)s")
    parser.add_argument("--probability", type=float, default=0.2, help="default: %(default)s")
    parser.add_argument("--run-name", help="default: derived by the pipeline")
    args = parser.parse_args()

    classifier: FrameClassifier
    if args.mock_type == "every-n":
        classifier = EveryNthClassifier(args.every_n)
        description = f"fake, flags every {args.every_n}th frame"
    elif args.mock_type == "random":
        classifier = RandomClassifier(args.probability)
        description = f"fake, flags frames with probability {args.probability}"
    else:
        classifier = ClaudeCliClassifier()
        description = f"Claude CLI (model={classifier.model}, effort={classifier.effort})"
    print(f"Classifier: {description}")
    print(f"Source: {args.url}")
    print(f"FPS: {args.fps}")

    saved = run(
        args.url,
        downloads_dir=Path(".runtime") / "downloads",
        runtime_dir=Path(".runtime"),
        run_name=args.run_name,
        fps=args.fps,
        classifier=classifier,
    )
    if saved:
        print(f"✓ Extracted {len(saved)} memes:")
        for path in saved:
            print(f"  {path}")
    else:
        print("No memes extracted.")


if __name__ == "__main__":
    main()
