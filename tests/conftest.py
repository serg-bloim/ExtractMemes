from pathlib import Path

import pytest

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample"


@pytest.fixture(scope="session")
def short_video() -> Path:
    """`sample/short.mp4` (78.56 s, 256x144, 25 fps); skips the test when the fixture is absent."""
    path = SAMPLE_DIR / "short.mp4"
    if not path.is_file():
        pytest.skip(f"fixture {path} is absent")
    return path
