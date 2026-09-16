import subprocess
import sys


def test_console_command_help():
    result = subprocess.run(
        ["extract-memes", "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "extract" in result.stdout.lower()


def test_module_invocation_help():
    result = subprocess.run(
        [sys.executable, "-m", "extract_memes", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "extract" in result.stdout.lower()
