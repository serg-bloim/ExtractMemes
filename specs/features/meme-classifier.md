---
title: "Meme Classifier (Claude CLI)"
status: ready
created: 2026-09-16
updated: 2026-09-16
author: ""
depends-on: ["project-setup"]
---

# Meme Classifier (Claude CLI)

## Problem Statement

For each sampled frame, the pipeline needs a yes/no judgment: is this one of the video's meme
reveals, or an ordinary frame? In the videos this project targets, a meme is shown as a
"glitch-framed meme card": one central card holding the meme, surrounded by grainy multicolored
VHS/TV static and crossed by bright horizontal glitch bands. Nearby look-alikes must be rejected:
portrait videos with blurred or black side bars, presenters with picture-in-picture overlays,
screenshots on plain backgrounds, and title or sponsor cards. Per
[ADR 004](../../decisions/004-claude-classifier-and-dual-resolution-download.md), Claude makes the
judgment through the `claude` CLI that's already installed and authenticated, so no API key and
no hand-trained model are needed.

## User Story

**Primary:**
As the ExtractMemes pipeline, I want to ask Claude whether a given frame image is a glitch-framed
meme card, so that I can flag its timecode for extraction without a hand-built model.

**Secondary:**
As the developer, I want to choose the Claude model and effort level used for classification, so
that I can trade cost and speed against accuracy while tuning.

## Acceptance Criteria

- [ ] AC1: `src/extract_memes/classifier.py` defines an abstract base class `FrameClassifier` with a
      single abstract method `is_meme(self, image_path: Path) -> bool`. It takes the path of an
      image file on disk, not an in-memory array, because the CLI reads files. Test doubles and
      dev fakes subclass it.
- [ ] AC2: `ClaudeCliClassifier(model: str = "claude-haiku-4-5-20251001", effort: str | None = "low", timeout: float = 60.0)`
      implements it and exposes `model`, `effort`, and `timeout` as public attributes.
- [ ] AC3: `is_meme` runs `subprocess.run` with this exact argument list:
      `["claude", "-p", "--output-format", "json", "--allowedTools=Read", "--model", <model>]`,
      then `["--effort", <effort>]` only if `effort` is truthy, then the prompt as the last
      argument. It uses `cwd=image_path.parent`, `capture_output=True`, `text=True`, and
      `timeout=self.timeout`. The prompt refers to the image **by bare file name only** (never the
      absolute path).
- [ ] AC4: The prompt is the verbatim "glitch-framed meme card" rubric under
      [Prompt (verbatim)](#prompt-verbatim) below, with `{filename}` replaced by `image_path.name`.
      Any change to the prompt text is a spec change.
- [ ] AC5: Parsing: `json.loads(stdout)["result"]`, then the first case-insensitive whole-word match
      of `YES` or `NO` (`\b(YES|NO)\b`). `YES` gives `True` and `NO` gives `False`. Surrounding
      whitespace and punctuation are fine (`"No."` → `False`).
- [ ] AC6: Any failure raises `RuntimeError` naming `image_path`. It never silently returns
      `True`/`False`. Failures include:
      the call times out (chained from `TimeoutExpired`);
      the process exits non-zero (the message includes stripped stderr);
      stdout isn't JSON or has no `result` key (the message includes the raw stdout);
      the result has no YES/NO word (the message includes the result text);
      or the `claude` executable isn't found. For that last case, catch `FileNotFoundError` and
      say that the Claude Code CLI must be installed, authenticated, and on `PATH`.
- [ ] AC7: Unit tests mock `subprocess.run` and never spawn a real `claude` process (that would be
      slow, cost real usage, and recursively launch Claude Code from its own test suite). They
      cover:
      `"YES"` → `True`, `"No."` → `False`;
      `--model`/`--effort` values appear in the command;
      `effort=None` omits `--effort`;
      `--allowedTools=Read` is a single `=`-joined argument;
      `cwd` is the image's parent, and the prompt contains the file name but not the parent path;
      non-zero exit, non-JSON stdout, missing `result`, an ambiguous answer (`"maybe"`), a timeout,
      and a missing binary (`FileNotFoundError`) each raise `RuntimeError`.

## Out of Scope

- Any non-Claude classifier (heuristic, local ML/CLIP, Anthropic API SDK). `FrameClassifier` allows
  adding one later without touching callers.
- Batching several frames into one `claude` call, or running calls in parallel. It's one frame,
  one process, sequentially. This is the dominant runtime cost (see Technical Notes).
- Confidence scores or explanations. A strict boolean is all the pipeline needs.
- Tuning the per-call Claude Code session overhead (see the last Technical Note). It's recorded as
  an open optimization in ADR 007, and it doesn't block the rebuild.
- Automated evaluation against the labeled frame set. That set exists (see Technical Notes), but
  scoring the prompt against it is a manual activity today.

## Prompt (verbatim)

Written by the user and used unchanged since commit `c96df5a`. Validated as "works well" (commit
`e5bb00e`). `{filename}` is the only substitution. The template is a Python triple-quoted string
that starts with `"""\` and ends with `\` + `"""`, so there's no leading or trailing newline.

```text
Look at the image at {filename} and answer with exactly one word: YES or NO.
The image may be a small, low-resolution video frame; judge its overall layout and texture, not fine details.

Answer YES only if the image is a "glitch-framed meme card", meaning ALL of these are true:
1. BACKGROUND IS DIGITAL STATIC. The area around the main content is not a real scene. It is VHS/TV-style glitch noise: a darkish, grainy field of tiny multicolored speckles (red, green, blue, magenta pixels), often smeared or streaked horizontally.
2. HORIZONTAL GLITCH BANDS. One or more thin, bright (white or pastel) horizontal scanline streaks run across the whole width of the frame, often passing over the central card as well.
3. ONE CENTRAL CARD. A single rectangle sits in the middle, about half the frame's width, with static filling both the left and right margins (and often strips above and below). The card holds a meme: a social-media post or comment thread, a chat/search/news screenshot, a cartoon or comic panel, or a photo with a caption.

Answer NO for everything else, including these look-alikes:
- Vertical videos or photos whose side areas are filled with a blurred, enlarged copy of the same picture. That side fill is soft and smooth, not grainy multicolored static.
- Screenshots or profile pages on a plain white or solid-color background.
- A presenter, TV studio, or street scene with a picture-in-picture card, QR code, or caption overlaid on it. The background is real filmed footage, not static.
- Title cards, sponsor/credits screens, logo or channel intros, and QR-code screens with cartoon or illustrated backgrounds, even if they are dark, colorful, textured, or smoky.
- Ordinary full-frame footage, even if it is blurry, compressed, or noisy.

Deciding test: look at the regions to the LEFT and RIGHT of the central content. Are they filled with colorful random pixel static crossed by horizontal glitch lines? If yes, answer YES. If they are a real scene, a blur, a flat color, or a designed graphic, answer NO.
The topic, language, humor, or emotional tone of the content does not matter.

Respond with only YES or NO, with no other text.
```

## Technical Notes

- **No new Python dependency.** This shells out to the `claude` binary on `PATH` (Claude Code;
  known-good 2.1.267).
- **Runtime prerequisite:** the machine running the pipeline must have `claude` installed and
  already authenticated. This is the deliberate ADR 004 choice over requiring
  `ANTHROPIC_API_KEY`. The code doesn't check for it beyond AC6's clear error.
- **Why `cwd` = the image's folder, plus a bare file name:** a non-interactive `-p` run can't answer
  a permission prompt. `--allowedTools=Read` pre-approves reading, and files inside the session's
  working directory are readable without granting extra directories. The prompt also stays free
  of absolute paths.
- **Pitfall: `--allowedTools` is variadic** (`--allowedTools, --allowed-tools <tools...>` in
  `claude --help`). Always pass it as the single token `--allowedTools=Read`. The space-separated
  form, `--allowedTools Read`, can swallow the following positional prompt as another tool name.
  The original spec text showed the space form; the code has always used `=`.
- **`--output-format json`** is used so the answer comes from the structured `result` field instead
  of scraped free text.
- **Effort values** accepted by the CLI flag: `low`, `medium`, `high`, `xhigh`, `max`. `haiku-4.5`
  with `low` has been used successfully for full runs.
- **What the classifier actually sees:** the JPEG that the pipeline writes to
  `.runtime/<run>/frames/` from the *worst*-quality download. That's typically 256x144 for YouTube
  (format 269), which is why the prompt says "may be a small, low-resolution video frame".
- **Measured latency (2026-09-16, haiku-4.5 / low, sequential):**
  - `sample/short.mp4`: 164 frames in ~43 min (median ~7.6s per frame, mean ~15.8s).
  - Test video `AElGyY97k_0`: 26 frames in ~4.5 min (~10.8s per frame).

  At that rate, a 62.7-minute video at 2 fps (7842 samples) would take roughly 17+ hours. Scaling
  is a known open problem (ADR 007 register).
- **Per-call session overhead (unverified, open):** each call starts a full Claude Code session with
  its working directory inside the project tree. It may load the project's `CLAUDE.md`, settings,
  and hooks as context, and it saves a session transcript per frame. Candidate flags to evaluate
  later: `--no-session-persistence`, `--setting-sources`, `--bare`. Not adopted: their effect on
  accuracy, cost, and latency hasn't been measured.
- **Answer parsing edge:** the first YES/NO word wins, so a chatty answer like "I can't say yes or
  no" parses as `YES`. It's acceptable because the prompt demands a one-word answer, and it hasn't
  been seen in practice.

### Prompt history (why the rubric looks the way it does)

| Version | Prompt | Observed result | Fix |
|---|---|---|---|
| v1 (ADR 004) | Generic: "read the image … answer YES or NO: is it a meme". Exact text not preserved in git. | First run on `short.mp4` at 1 fps flagged a presenter with a small inset thumbnail (`frame_20.00s`, `frame_24.00s`), not a meme. | v2 |
| v2 (ADR 005) | "Read the image at {filename}. In this video, a meme reveal looks like: a meme-style image (captioned image, comparison, or reaction image) centered in the frame, with the rest of the frame just dark/black background, and the whole frame covered in analog TV-static-like noise. Answer with exactly one word, YES or NO: does this frame match that pattern, as opposed to an ordinary frame (e.g. a presenter talking, with no centered meme image and no static/noise)?" | 2 fps rerun on `short.mp4` flagged 17 frames, and only 2 were real (10.56s, 28.80s). 15 false positives were portrait videos in landscape frames: blurred-enlarged side fill (31.68–37.92s) and plain black pillarbox bars (73.44–75.84s). "Centered image + dark background" matched pillarboxing. | v3 |
| v3 (current) | The user-authored rubric above: requires static texture **and** horizontal glitch bands **and** one central card, lists the look-alikes explicitly, and adds a "look left/right of the card" deciding test. | 2 fps rerun on `short.mp4` (`.runtime/_playground/default_run`) flagged exactly 2 frames, `10.56s` and `28.80s`, both true glitch cards, with no false positives. | none |

### Reference material for tuning (not in git)

- `.runtime/experiment/positive/`: 15 labeled positives. `.runtime/experiment/negative/`: 23
  labeled negatives. All are 256x144 PNGs named `quick_frame_<min>-<sec>.png`, taken (by their
  resolution and timestamps up to 58:56) from `sample/full.mp4`. The user built these by hand to
  write the v3 rubric.
  - **Positives:** static-framed cards holding social-media posts and comment threads, chat and
    search screenshots, comic panels, and captioned photos.
  - **Negatives:** a sponsor-thanks card, a profile page on white, a presenter with a
    picture-in-picture profile card or portrait clip, a menu close-up, a QR code over a street
    scene, blurred-pillarbox portrait videos, a stylized title card, studio group shots, a
    cartoon QR-code card, and plain presenter shots.
  - **Risk:** `.runtime/` is gitignored and described as disposable run output. Move this set somewhere
    durable (e.g. `sample/experiment/`) before any cleanup.
- `sample/quick_frame_9-32.png`: one more positive example.
- `playground/playground.py::test_classify_one_frame` classifies a single known-positive frame
  (`short.mp4` at 10.56s). It's the quickest check after a prompt edit (see the dev-harness spec).

## Open Questions

All resolved:

- Q1: Anthropic API or Claude CLI? **Claude CLI** (`claude -p`). No API key is configured, and the CLI
  is already authenticated. See ADR 004 Option B.
- Q2: What if Claude's answer is ambiguous? **Raise.** Don't guess: a silent default would corrupt
  the output with no way to notice.
- Q3: Whose prompt? **The user's rubric, verbatim** (v3). Prompt changes happen only through this
  spec.
- Q4: Which model and effort by default? **`claude-haiku-4-5-20251001` at `low`.** A cheap model at
  low effort is enough for a binary layout judgment. Both are configurable through the
  constructor, `pipeline.run(classifier_model=…, classifier_effort=…)`, and the CLI flags
  `--classifier-model` / `--classifier-effort` (see the extraction-pipeline spec).
- Q5: How does Claude get the image? **As a file on disk.** Set the process `cwd` to the image's
  folder, name the file in the prompt, and pre-approve `Read`.
- Q6: What if `claude` isn't installed? **Raise `RuntimeError` with an actionable message** (AC6).
  Previously the raw `FileNotFoundError` leaked out.

## Changelog

- 2026-09-16: Implemented as part of "implement the whole project." Chose the Claude CLI over
  the Anthropic API specifically because no API key was configured in this environment and the
  `claude` binary was already present and authenticated. See ADR 004.
- 2026-09-16: The user reviewed the first real run's output and identified the actual meme-reveal
  pattern (centered image, dark background, analog TV static/noise) that the generic prompt was
  missing. Rewrote `_PROMPT_TEMPLATE` to describe that pattern explicitly. See
  [ADR 005](../../decisions/005-runtime-layout-and-classifier-checkpoint.md).
- 2026-09-16: The 2fps rerun (per ADR 005) still false-positived on portrait video with pillarbox
  bars. The user supplied their own "glitch-framed meme card" rubric (grainy multicolored static +
  horizontal glitch bands + one central card, with explicit look-alike rejections) and asked to
  drop it into the code verbatim. Replaced `_PROMPT_TEMPLATE` with that exact text
  (`<IMAGE_PATH>` → `{filename}`); no other logic changed.
- 2026-09-16: The user asked how to configure the classification model/effort, which was
  previously hardcoded (`model` had a constructor default, `effort` wasn't sent at all). Added
  `effort` to `ClaudeCliClassifier.__init__` (default `"low"`, appends `--effort` only when set),
  and exposed both as `--classifier-model`/`--classifier-effort` on the CLI, threaded through
  `pipeline.run(classifier_model=..., classifier_effort=...)`.
- 2026-09-16 (commit `e5bb00e`, "new criteria works well"): The v3 rubric was validated on a real
  2 fps run of `sample/short.mp4`: exactly the two true glitch cards (10.56s, 28.80s) flagged, and
  the 15 v2 false positives gone.
- 2026-09-16: Documentation consolidation for the planned rebuild
  ([ADR 007](../../decisions/007-documentation-consolidation-for-rebuild.md)). The prompt existed
  only in code, so embedded it verbatim in this spec (AC4). Added a prompt-history table with the
  v2 text and each version's failure mode. Pinned the exact CLI argument list and the `cwd`/file
  name contract (AC3), and documented the variadic `--allowedTools` pitfall. Added the
  missing-binary error (AC6), measured latency, the labeled evaluation set and its at-risk
  location, and the unverified per-call session overhead. Reset status to `ready` with unchecked
  ACs because the implementation will be erased and rebuilt.
