"""Manual scan-only runs to start one at a time from the IDE.

Each run does the scan phase only (`no_images=True`): the worst-quality copy is sampled and
classified, and nothing is extracted, so there is no best-quality download and no `clean/` or
`high-res/` output. What it writes, under `.runtime/_playground/scan/`:

- `frames/`: every sampled frame;
- `low-res/`: the flagged frames, one file each (merging happens after the scan, so it doesn't
  apply here);
- `timecodes.txt`: one line per meme, from the flagged scan timestamps.

The runs use the pipeline's default heuristic classifier, which is free; pass
`classifier_type="claude"` to `_scan` for the real one (slow, and costs usage). Each run first
deletes that run folder, so the entries share it and the last one run is what is left. The functions are
named `test_*` only so IDE pytest integrations show a run icon; they assert nothing, and a bare
`pytest` collects nothing from here.

Downloads go to `.runtime/downloads/`, not under the playground folder. The URL runs reuse the
worst-quality copy already there (yt-dlp skips a file it has), though they still ask YouTube for
the video's metadata, so they need network access (and a proxy, if you use one). The local-file
run downloads nothing.

`python playground/scan_playground.py` runs `test_scan_video_url()`.
"""

import shutil
from pathlib import Path

from extract_memes.pipeline import run

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SHORT_VIDEO = PROJECT_ROOT / "sample" / "short.mp4"
PLAYGROUND_DIR = PROJECT_ROOT / ".runtime" / "_playground"
DOWNLOADS_DIR = PROJECT_ROOT / ".runtime" / "downloads"
# The video whose worst-quality copy (`Ij427pW96aI_worst.mp4`) is already in `.runtime/downloads/`.
VIDEO_URL = "https://www.youtube.com/watch?v=Ij427pW96aI"
RUN_NAME = "scan"


def _scan(source: Path | str, **kwargs) -> None:
    run_dir = PLAYGROUND_DIR / RUN_NAME
    # Start from an empty run folder, so output from an earlier run doesn't mix in. Only here: the
    # pipeline itself never deletes anything.
    shutil.rmtree(run_dir, ignore_errors=True)
    run(
        str(source),
        downloads_dir=DOWNLOADS_DIR,
        runtime_dir=PLAYGROUND_DIR,
        run_name=RUN_NAME,
        no_images=True,
        save_frames=True,
        save_low_res=True,
        save_timecodes=True,
        **kwargs,
    )
    timecodes = run_dir / "timecodes.txt"
    lines = timecodes.read_text(encoding="utf-8").splitlines() if timecodes.is_file() else []
    print(f"{len(lines)} memes flagged; scan output in {run_dir}")
    for line in lines:
        print(f"  {line}")


def test_scan_video_url():
    _scan(VIDEO_URL)


def test_scan_video_url_different_fps():
    _scan(VIDEO_URL, fps=2)


def test_scan_short_video():
    _scan(SHORT_VIDEO)


if __name__ == "__main__":
    test_scan_video_url()
