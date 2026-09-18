"""Classify frame images as memes or not, using Claude through the `claude` CLI."""

import json
import re
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

import cv2
import numpy as np

# The user-authored "glitch-framed meme card" rubric, verbatim from the meme-classifier spec.
# `{filename}` is the only substitution. Any change to this text is a spec change.
PROMPT_TEMPLATE = """\
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

Respond with only YES or NO, with no other text.\
"""

_ANSWER = re.compile(r"\b(YES|NO)\b", re.IGNORECASE)


class FrameClassifier(ABC):
    """Decides whether an image file on disk shows a meme."""

    @abstractmethod
    def is_meme(self, image_path: Path) -> bool:
        """Return whether the image at `image_path` is a meme."""

    def is_meme_frame(self, frame: np.ndarray) -> bool:
        """Classify a decoded video frame (BGR uint8 array).

        By default, writes the frame to a temporary file and calls is_meme.
        Subclasses may override to classify in-memory. The temporary file is
        always cleaned up, even if is_meme raises.
        """
        tmpdir = tempfile.TemporaryDirectory()
        try:
            tmp_path = Path(tmpdir.name) / "frame.jpg"
            if not cv2.imwrite(str(tmp_path), frame):
                raise RuntimeError(f"Could not write image: {tmp_path}")
            return self.is_meme(tmp_path)
        finally:
            tmpdir.cleanup()


class ClaudeCliClassifier(FrameClassifier):
    """Asks Claude, via `claude -p`, whether a frame is a glitch-framed meme card."""

    def __init__(
        self,
        model: str = "claude-haiku-4-5-20251001",
        effort: str | None = "low",
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        self.effort = effort
        self.timeout = timeout

    def is_meme(self, image_path: Path) -> bool:
        # `--allowedTools` is variadic, so it must stay one `=`-joined token or it swallows the prompt.
        command = ["claude", "-p", "--output-format", "json", "--allowedTools=Read", "--model", self.model]
        if self.effort:
            command += ["--effort", self.effort]
        # A `-p` run can't answer permission prompts. Running in the image's folder and naming the
        # file bare keeps the read inside the session's working directory.
        command.append(PROMPT_TEMPLATE.format(filename=image_path.name))

        try:
            completed = subprocess.run(
                command,
                cwd=image_path.parent,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Could not classify {image_path}: {exc}. The Claude Code CLI (`claude`) must be "
                "installed, authenticated, and on PATH."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Classifying {image_path} timed out after {self.timeout}s") from exc

        if completed.returncode != 0:
            raise RuntimeError(
                f"claude exited with code {completed.returncode} while classifying {image_path}: "
                f"{completed.stderr.strip()}"
            )
        try:
            result = json.loads(completed.stdout)["result"]
        except (ValueError, KeyError, TypeError) as exc:
            raise RuntimeError(
                f"Unexpected claude output while classifying {image_path}: {completed.stdout!r}"
            ) from exc

        match = _ANSWER.search(result) if isinstance(result, str) else None
        if match is None:
            raise RuntimeError(f"No YES/NO answer from claude for {image_path}: {result!r}")
        return match.group(1).upper() == "YES"
