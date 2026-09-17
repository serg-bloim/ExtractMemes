import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from extract_memes.__main__ import main

HELP_COMMANDS = [["extract-memes"], [sys.executable, "-m", "extract_memes"]]


@pytest.mark.parametrize("command", HELP_COMMANDS)
def test_help(command, tmp_path):
    result = subprocess.run([*command, "--help"], capture_output=True, text=True, cwd=tmp_path)

    assert result.returncode == 0
    assert "extract" in result.stdout.lower()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("command", HELP_COMMANDS)
def test_no_arguments_prints_usage(command, tmp_path):
    result = subprocess.run(command, capture_output=True, text=True, cwd=tmp_path)

    assert result.returncode == 0
    assert result.stdout.startswith("usage: extract-memes")
    assert list(tmp_path.iterdir()) == []


def test_defaults_are_passed_to_pipeline(capsys):
    with mock.patch("extract_memes.pipeline.run", return_value=[]) as run:
        main(["sample/short.mp4"])

    run.assert_called_once_with(
        "sample/short.mp4",
        downloads_dir=Path("downloads"),
        runtime_dir=Path(".runtime"),
        run_name=None,
        fps=2.0,
        classifier_model="claude-haiku-4-5-20251001",
        classifier_effort="low",
    )
    assert capsys.readouterr().out == ""


def test_options_are_passed_to_pipeline_and_paths_printed(capsys):
    saved = [Path("out/saved/frame_000264_10.56s.jpg"), Path("out/saved/frame_000720_28.80s.jpg")]
    with mock.patch("extract_memes.pipeline.run", return_value=saved) as run:
        main([
            "https://youtu.be/AElGyY97k_0",
            "--fps", "0.5",
            "--downloads-dir", "dl",
            "--runtime-dir", "out",
            "--run-name", "demo",
            "--classifier-model", "claude-sonnet-5",
            "--classifier-effort", "xhigh",
        ])  # fmt: skip

    run.assert_called_once_with(
        "https://youtu.be/AElGyY97k_0",
        downloads_dir=Path("dl"),
        runtime_dir=Path("out"),
        run_name="demo",
        fps=0.5,
        classifier_model="claude-sonnet-5",
        classifier_effort="xhigh",
    )
    assert capsys.readouterr().out.splitlines() == [str(path) for path in saved]


def test_invalid_effort_is_rejected():
    with pytest.raises(SystemExit) as excinfo:
        main(["sample/short.mp4", "--classifier-effort", "extreme"])

    assert excinfo.value.code == 2
