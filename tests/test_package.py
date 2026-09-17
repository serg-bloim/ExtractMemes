import subprocess
import sys


def test_import():
    import extract_memes  # noqa: F401


def test_importing_every_module_has_no_side_effects(tmp_path):
    # A fresh interpreter, so modules already imported by other tests don't hide side effects.
    script = """
import importlib, os, pkgutil
import extract_memes

path_before = os.environ.get("PATH")
for module in pkgutil.walk_packages(extract_memes.__path__, "extract_memes."):
    importlib.import_module(module.name)
assert os.environ.get("PATH") == path_before, "PATH changed on import"
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []
