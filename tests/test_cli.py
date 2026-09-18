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
        classifier_type="heuristic",
        classifier_model="claude-haiku-4-5-20251001",
        classifier_effort="low",
        save_frames=False,
        save_low_res=False,
        clean_method="clean_rows",
        save_high_res=False,
    )
    assert capsys.readouterr().out == ""


def test_options_are_passed_to_pipeline_and_paths_printed(capsys):
    saved = [Path("out/demo/clean/meme_001.png"), Path("out/demo/clean/meme_002.png")]
    with mock.patch("extract_memes.pipeline.run", return_value=saved) as run:
        main([
            "https://youtu.be/AElGyY97k_0",
            "--fps", "0.5",
            "--downloads-dir", "dl",
            "--runtime-dir", "out",
            "--run-name", "demo",
            "--classifier", "claude",
            "--classifier-model", "claude-sonnet-5",
            "--classifier-effort", "xhigh",
            "--save-frames",
            "--save-low-res",
            "--clean-method", "median",
            "--save-high-res",
        ])  # fmt: skip

    run.assert_called_once_with(
        "https://youtu.be/AElGyY97k_0",
        downloads_dir=Path("dl"),
        runtime_dir=Path("out"),
        run_name="demo",
        fps=0.5,
        classifier_type="claude",
        classifier_model="claude-sonnet-5",
        classifier_effort="xhigh",
        save_frames=True,
        save_low_res=True,
        clean_method="median",
        save_high_res=True,
    )
    assert capsys.readouterr().out.splitlines() == [str(path) for path in saved]


@pytest.mark.parametrize(
    ("flag", "expected"),
    [
        ("--save-frames", {"save_frames": True, "save_low_res": False}),
        ("--save-low-res", {"save_frames": False, "save_low_res": True}),
        ("--save-high-res", {"save_frames": False, "save_high_res": True}),
    ],
)
def test_each_save_flag_sets_only_its_option(flag, expected):
    with mock.patch("extract_memes.pipeline.run", return_value=[]) as run:
        main(["sample/short.mp4", flag])

    assert {key: run.call_args.kwargs[key] for key in expected} == expected


def test_help_describes_the_output_folders(capsys, monkeypatch):
    # argparse wraps to the terminal width and may break a line at the hyphen in `<run-name>`.
    monkeypatch.setenv("COLUMNS", "1000")
    with pytest.raises(SystemExit):
        main(["--help"])

    help_text = capsys.readouterr().out
    assert "<runtime-dir>/<run-name>/high-res/" in help_text
    assert "saved/" not in help_text
    assert "<runtime-dir>/<run-name>/frames/" in help_text
    assert "<runtime-dir>/<run-name>/low-res/" in help_text
    assert "<runtime-dir>/<run-name>/clean/" in help_text
    assert "<runtime-dir>/<run-name>/high-res/meme_<n>/" in help_text


def test_clean_method_none_disables_cleaning():
    with mock.patch("extract_memes.pipeline.run", return_value=[]) as run:
        main(["sample/short.mp4", "--clean-method", "none"])

    assert run.call_args.kwargs["clean_method"] is None


def test_invalid_clean_method_is_rejected():
    with pytest.raises(SystemExit) as excinfo:
        main(["sample/short.mp4", "--clean-method", "average"])

    assert excinfo.value.code == 2


def test_invalid_effort_is_rejected():
    with pytest.raises(SystemExit) as excinfo:
        main(["sample/short.mp4", "--classifier-effort", "extreme"])

    assert excinfo.value.code == 2


def test_invalid_classifier_is_rejected():
    with pytest.raises(SystemExit) as excinfo:
        main(["sample/short.mp4", "--classifier", "clip"])

    assert excinfo.value.code == 2
