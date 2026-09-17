from pathlib import Path

import pytest

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="session")
def short_video() -> Path:
    """`sample/short.mp4` (78.56 s, 256x144, 25 fps); skips the test when the fixture is absent."""
    path = SAMPLE_DIR / "short.mp4"
    if not path.is_file():
        pytest.skip(f"fixture {path} is absent")
    return path


@pytest.fixture(scope="session")
def labeled_positive_paths() -> list[Path]:
    """Paths to labeled positive frames in data/labeled_dataset/positive/; skips if absent."""
    dir_path = DATA_DIR / "labeled_dataset" / "positive"
    if not dir_path.is_dir():
        pytest.skip(f"fixture {dir_path} is absent")
    return sorted(dir_path.glob("*.png"))


@pytest.fixture(scope="session")
def labeled_negative_paths() -> list[Path]:
    """Paths to labeled negative frames in data/labeled_dataset/negative/; skips if absent."""
    dir_path = DATA_DIR / "labeled_dataset" / "negative"
    if not dir_path.is_dir():
        pytest.skip(f"fixture {dir_path} is absent")
    return sorted(dir_path.glob("*.png"))
