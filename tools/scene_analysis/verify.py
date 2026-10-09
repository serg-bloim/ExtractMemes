"""Have Claude judge the scenes whose scores sit nearest the production threshold, and store its verdicts.

Scenes come from the database, the images from the labeler cache and the downloaded video, and every
verdict goes back in through `SceneStore.set_claude_status`.
"""

import json
import re
import contextlib
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from extract_memes.classifier import PROMPT_TEMPLATE

from .store import Scene, SceneStore

# What Claude is asked about a batch of scenes: the rubric of the classifier, then one answer per image.
PROMPT = """\
You are given {count} scenes of a video. Each scene has two images, which are frames of that scene:
{listing}

Judge every image separately against the rubric below. Ignore the rubric's instruction to answer with a single
word; use the answer format given after it.

--- RUBRIC ---
{rubric}
--- END RUBRIC ---

Answer with a single JSON object and nothing else, with one entry per scene, numbered as above:
{{"scenes": [{{"scene": 1, "first": "YES" or "NO", "second": "YES" or "NO", "reason": "<one short sentence>"}}, ...]}}
where "first" is the answer for the scene's first image and "second" for its second image.\
"""

_JSON = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class Judgement:
    """Claude's answer for the lowest-score frame (`low`) and the highest-score frame (`high`) of a scene."""

    low: bool
    high: bool
    reason: str = ""


@dataclass
class Result:
    checked: int = 0
    verdicts: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=lambda: {"frames": 0.0, "claude": 0.0, "verdicts": 0.0})  # seconds per stage
    calls: int = 0  # Claude calls made


@contextlib.contextmanager
def _timed(result: "Result", stage: str):
    started = time.perf_counter()
    try:
        yield
    finally:
        result.timings[stage] += time.perf_counter() - started


def format_timings(db: dict[str, float], select: float, result: "Result | None", total: float) -> str:
    """The `--dbg` report: seconds per stage. `db` is `SceneStore.timings` (load and save of the file)."""
    stages = [("database load", db["load"]), ("select scenes", select)]
    if result is not None:
        calls = f" ({result.calls} calls, {result.timings['claude'] / result.calls:.1f}s each)" if result.calls else ""
        stages += [("frames", result.timings["frames"]), ("claude" + calls, result.timings["claude"]),
                   ("store verdicts", result.timings["verdicts"])]
    stages.append(("database save", db["save"]))
    width = max(len(name) for name, _ in stages + [("total", 0)])
    lines = [f"  {name:<{width}}  {seconds:8.2f}s  {seconds / total:5.1%}" if total else f"  {name:<{width}}  {seconds:8.2f}s"
             for name, seconds in stages]
    lines.append(f"  {'total':<{width}}  {total:8.2f}s")
    return "timings:\n" + "\n".join(lines)


def distance_from_threshold(stats: dict) -> float:
    """0 if the scene's scores straddle the threshold, else how far its nearest score is from it."""
    threshold = stats["threshold"]
    if stats["min"] <= threshold <= stats["max"]:
        return 0.0
    return min(abs(stats["min"] - threshold), abs(stats["max"] - threshold))


def select(store: SceneStore, criterion: str, top: int, recheck: bool = False) -> list[Scene]:
    """The `top` scenes nearest the threshold of `criterion` (ties keep database order).

    Scenes without a condition on the criterion are ignored; scenes with a Claude status are skipped unless `recheck`.
    """
    def usable(scene: Scene) -> bool:
        stats = scene["stats"].get(criterion)
        return stats is not None and stats["threshold"] is not None and (recheck or scene["claude"] is None)

    scenes = store.select_scenes(usable).data
    scenes.sort(key=lambda s: distance_from_threshold(s["stats"][criterion]))
    return scenes[:top]


def extreme_frames(scores: np.ndarray, first: int, last: int) -> tuple[int, int]:
    """Frame indexes with the lowest and the highest score among `first..last`."""
    window = scores[first:last + 1]
    return first + int(np.argmin(window)), first + int(np.argmax(window))


def verdict_of(judgement: Judgement) -> str:
    if judgement.low and judgement.high:
        return "meme"
    if not judgement.low and not judgement.high:
        return "not_meme"
    return "unsure"


def check_of(stats: dict) -> str:
    """`miss` asks whether an unflagged scene is a meme; `false_positive` whether a (partly) flagged one is not."""
    return "miss" if stats["share_flagged"] == 0 else "false_positive"


def parse_answers(text: str, count: int) -> list[Judgement | None]:
    """Read Claude's JSON answer for a batch of `count` scenes: one entry per scene, None where it is missing or invalid.

    Raises ValueError if the text holds no JSON answer at all.
    """
    match = _JSON.search(text)
    if match is None:
        raise ValueError(f"no JSON object in {text!r}")
    try:
        entries = json.loads(match.group(0))["scenes"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"unexpected answer {text!r}") from exc
    judgements: list[Judgement | None] = [None] * count
    for entry in entries if isinstance(entries, list) else []:
        try:
            number = int(entry["scene"])
            answers = [str(entry[name]).strip().upper() for name in ("first", "second")]
        except (ValueError, KeyError, TypeError):
            continue
        if 1 <= number <= count and all(a in ("YES", "NO") for a in answers):
            judgements[number - 1] = Judgement(answers[0] == "YES", answers[1] == "YES", str(entry.get("reason", "")).strip())
    return judgements


class ClaudeJudge:
    """Asks Claude, through `claude -p`, about the two frames of each scene of a batch, in one call."""

    def __init__(self, model: str = "claude-haiku-4-5-20251001", effort: str | None = "low", timeout: float = 300.0) -> None:
        self.model, self.effort, self.timeout = model, effort, timeout

    def __call__(self, pairs: list[tuple[Path, Path]]) -> list[Judgement | None]:
        """One judgement per `(low image, high image)` pair, None for a scene Claude didn't answer properly.

        The images must be in one folder, which is where `claude` runs.
        """
        rubric = PROMPT_TEMPLATE.format(filename="the image")
        listing = "\n".join(f"Scene {n}: first image {low.name}, second image {high.name}" for n, (low, high) in enumerate(pairs, 1))
        prompt = PROMPT.format(count=len(pairs), listing=listing, rubric=rubric)
        command = ["claude", "-p", "--output-format", "json", "--allowedTools=Read", "--model", self.model]
        if self.effort:
            command += ["--effort", self.effort]
        command.append(prompt)
        try:
            completed = subprocess.run(command, cwd=pairs[0][0].parent, capture_output=True, text=True, timeout=self.timeout)
        except FileNotFoundError as exc:
            raise RuntimeError(f"{exc}. The Claude Code CLI (`claude`) must be installed, authenticated, and on PATH.") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"claude timed out after {self.timeout}s") from exc
        if completed.returncode != 0:
            raise RuntimeError(f"claude exited with code {completed.returncode}: {completed.stderr.strip()}")
        try:
            result = json.loads(completed.stdout)["result"]
        except (ValueError, KeyError, TypeError) as exc:
            raise RuntimeError(f"unexpected claude output: {completed.stdout!r}") from exc
        return parse_answers(result if isinstance(result, str) else "", len(pairs))


class FrameSource:
    """Per-frame scores and full-size frames of the videos already downloaded, one index per (video, format)."""

    def __init__(self, downloads: Path, cache_root: Path) -> None:
        self.downloads, self.cache_root = downloads, cache_root
        self._open: dict[tuple[str, str], tuple] = {}

    def _get(self, video_id: str, format_id: str):
        key = (video_id, format_id)
        if key not in self._open:
            from tools.labeling.index import FrameReader, build

            found = sorted(self.downloads.glob(f"{video_id}_{format_id}.*"))
            if not found:
                raise FileNotFoundError(f"{video_id}_{format_id} is not downloaded in {self.downloads} (run populate)")
            index = build(found[0], self.cache_root / f"{video_id}_{format_id}")
            self._open[key] = (index, FrameReader(found[0], index.pts))
        return self._open[key]

    def scores(self, video_id: str, format_id: str, criterion: str) -> np.ndarray:
        index, _ = self._get(video_id, format_id)
        if criterion not in index.scores:
            raise KeyError(f"no scores for {criterion!r} in {video_id}_{format_id}")
        return index.scores[criterion]

    def frame(self, video_id: str, format_id: str, frame_index: int) -> np.ndarray:
        return self._get(video_id, format_id)[1].get(frame_index)

    def close(self) -> None:
        for _, reader in self._open.values():
            reader.close()
        self._open.clear()


def verify(store: SceneStore, scenes: list[Scene], criterion: str, source,
           judge: Callable[[list[tuple[Path, Path]]], list[Judgement | None]], batch_size: int = 10,
           progress: Callable[[str], None] = lambda message: None) -> Result:
    """Judge each scene's lowest- and highest-score frames, `batch_size` scenes per call, and store the verdicts.

    The run is one database session (`store.batch()`): the file is read once and written once at the end.

    `source` offers `scores(video, format, criterion)` and `frame(video, format, index)`. A scene that fails
    (no video, no scores, no valid answer, a rejected write) is listed in `Result.errors` and skipped; a failed
    call fails the scenes of its batch.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    result = Result()
    # One database session for the whole run: the file is read once and written once, when the session closes.
    # Ctrl-C ends the run normally, so what was judged so far is still saved.
    with store.batch():
        try:
            _run(store, scenes, criterion, source, judge, batch_size, progress, result)
        except KeyboardInterrupt:
            result.errors.append("interrupted: the verdicts so far are saved")
    return result


def _run(store, scenes, criterion, source, judge, batch_size, progress, result) -> None:
    for start in range(0, len(scenes), batch_size):
        with tempfile.TemporaryDirectory() as tmp:
            ready = []  # (scene, low frame, high frame, image pair)
            for scene in scenes[start:start + batch_size]:
                try:
                    with _timed(result, "frames"):
                        video, fmt = scene["video_id"], scene["format_id"]
                        low, high = extreme_frames(source.scores(video, fmt, criterion), scene["first_frame"], scene["last_frame"])
                        pair = []
                        for name, index in (("low", low), ("high", high)):
                            path = Path(tmp) / f"scene{len(ready) + 1}_{name}_frame_{index}.jpg"
                            if not cv2.imwrite(str(path), source.frame(video, fmt, index)):
                                raise RuntimeError(f"could not write {path}")
                            pair.append(path)
                except Exception as exc:  # one bad scene must not stop the run
                    result.errors.append(f"{_where(scene)}: {type(exc).__name__}: {exc}")
                    continue
                ready.append((scene, low, high, tuple(pair)))
            if not ready:
                continue
            try:
                result.calls += 1
                with _timed(result, "claude"):
                    judgements = judge([pair for *_, pair in ready])
            except Exception as exc:
                result.errors.extend(f"{_where(scene)}: {type(exc).__name__}: {exc}" for scene, *_ in ready)
                continue
            for (scene, low, high, _), judgement in zip(ready, judgements):
                if judgement is None:
                    result.errors.append(f"{_where(scene)}: no valid answer from Claude")
                    continue
                verdict = verdict_of(judgement)
                reason = f"frame {low} {'YES' if judgement.low else 'NO'}, frame {high} {'YES' if judgement.high else 'NO'}: {judgement.reason}"
                with _timed(result, "verdicts"):
                    response = store.set_claude_status(scene["video_id"], scene["format_id"], scene["first_frame"], verdict, reason,
                                                       check_of(scene["stats"][criterion]))
                if not response.ok:
                    result.errors.append(f"{_where(scene)}: {response.status} {response.message}")
                    continue
                result.checked += 1
                result.verdicts[verdict] = result.verdicts.get(verdict, 0) + 1
                progress(f"[{result.checked + len(result.errors)}/{len(scenes)}] {_where(scene)}: {verdict}")


def _where(scene: Scene) -> str:
    return f"{scene['video_id']}/{scene['format_id']} frames {scene['first_frame']}-{scene['last_frame']}"
