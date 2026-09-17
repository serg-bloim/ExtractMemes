import json
import re
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from extract_memes.classifier import PROMPT_TEMPLATE, ClaudeCliClassifier, FrameClassifier

SPEC = Path(__file__).resolve().parent.parent / "specs" / "features" / "meme-classifier.md"
IMAGE = Path("/runs/short/frames/frame_000264_10.56s.jpg")


def completed(result="YES", returncode=0, stdout=None, stderr=""):
    if stdout is None:
        stdout = json.dumps({"type": "result", "result": result})
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture
def run():
    with mock.patch("extract_memes.classifier.subprocess.run") as run:
        run.return_value = completed()
        yield run


def classify(run, classifier=None, **completed_kwargs):
    if completed_kwargs:
        run.return_value = completed(**completed_kwargs)
    return (classifier or ClaudeCliClassifier()).is_meme(IMAGE)


def command(run) -> list[str]:
    run.assert_called_once()
    return run.call_args.args[0]


def test_frame_classifier_is_abstract():
    with pytest.raises(TypeError):
        FrameClassifier()


def test_defaults():
    classifier = ClaudeCliClassifier()

    assert classifier.model == "claude-haiku-4-5-20251001"
    assert classifier.effort == "low"
    assert classifier.timeout == 60.0


@pytest.mark.parametrize(
    ("result", "expected"),
    [("YES", True), ("No.", False), ("  yes\n", True), ("NO", False)],
)
def test_parses_answer(run, result, expected):
    assert classify(run, result=result) is expected


def test_command_line(run):
    classify(run, ClaudeCliClassifier(model="claude-sonnet-5", effort="high", timeout=12.5))

    assert command(run) == [
        "claude", "-p", "--output-format", "json", "--allowedTools=Read",
        "--model", "claude-sonnet-5",
        "--effort", "high",
        PROMPT_TEMPLATE.format(filename=IMAGE.name),
    ]  # fmt: skip
    assert run.call_args.kwargs == {
        "cwd": IMAGE.parent,
        "capture_output": True,
        "text": True,
        "timeout": 12.5,
    }


def test_effort_none_omits_effort_flag(run):
    classify(run, ClaudeCliClassifier(effort=None))

    assert "--effort" not in command(run)
    assert command(run)[-2:-1] == ["claude-haiku-4-5-20251001"]


def test_allowed_tools_is_a_single_argument(run):
    classify(run)

    assert "--allowedTools=Read" in command(run)
    assert "--allowedTools" not in command(run)
    assert "Read" not in command(run)


def test_prompt_names_the_file_but_not_its_folder(run):
    classify(run)

    prompt = command(run)[-1]
    assert IMAGE.name in prompt
    assert str(IMAGE.parent) not in prompt
    assert run.call_args.kwargs["cwd"] == IMAGE.parent


def test_prompt_matches_spec_verbatim():
    spec = SPEC.read_text()
    block = re.search(r"## Prompt \(verbatim\).*?```text\n(.*?)\n```", spec, re.S).group(1)

    assert PROMPT_TEMPLATE == block


def test_non_zero_exit_raises(run):
    with pytest.raises(RuntimeError, match=r"frame_000264_10\.56s\.jpg.*not logged in"):
        classify(run, returncode=1, stdout="", stderr="  not logged in\n")


@pytest.mark.parametrize("stdout", ["not json", json.dumps({"type": "result"}), "[]"])
def test_unexpected_stdout_raises(run, stdout):
    with pytest.raises(RuntimeError, match="frame_000264_10.56s.jpg") as excinfo:
        classify(run, stdout=stdout)

    assert stdout in str(excinfo.value)


def test_ambiguous_answer_raises(run):
    with pytest.raises(RuntimeError, match=r"frame_000264_10\.56s\.jpg.*maybe"):
        classify(run, result="maybe")


def test_timeout_raises(run):
    timeout = subprocess.TimeoutExpired(cmd="claude", timeout=60.0)
    run.side_effect = timeout

    with pytest.raises(RuntimeError, match="frame_000264_10.56s.jpg") as excinfo:
        classify(run)

    assert excinfo.value.__cause__ is timeout


def test_missing_claude_binary_raises(run):
    run.side_effect = FileNotFoundError(2, "No such file or directory", "claude")

    with pytest.raises(RuntimeError, match=r"frame_000264_10\.56s\.jpg.*installed, authenticated"):
        classify(run)
