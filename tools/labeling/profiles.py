"""Saved sets of the labeler's classifier filters ("profiles"), one YAML file each.

Files live in data/datasets/profiles/classifier/<name>.yaml:

    schema: 1
    name: profile1
    filters:
      human_label: anything_but_meme   # any | meme | not_meme | unlabeled | anything_but_meme
      classifier: flagged              # any | flagged | not_flagged
      ranges:                          # per criterion; a missing bound is open
        band: {min: 180.0}
      invert: [band]                   # filters that match what does NOT pass them (omitted when none)
"""

import math
import re
from pathlib import Path

PROFILES_DIR = Path("data/datasets/profiles/classifier")
DEFAULT_NAME = "profile1"
SCHEMA = 1
HUMAN_LABELS = ("any", "meme", "not_meme", "unlabeled", "anything_but_meme")
CLASSIFIER_VERDICTS = ("any", "flagged", "not_flagged")
_NAME = re.compile(r"[\w-]{1,64}")


class ProfileError(ValueError):
    """A profile name or its filters are not acceptable."""


class ProfileNotFound(ProfileError):
    pass


def check_name(name) -> str:
    """The name if it is a plain file name (letters, digits, `_`, `-`; at most 64), else `ProfileError`."""
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ProfileError("a profile name is 1-64 letters, digits, '_' or '-'")
    return name


def profile_path(name: str, directory: Path = PROFILES_DIR) -> Path:
    return directory / f"{check_name(name)}.yaml"


def list_profiles(directory: Path = PROFILES_DIR) -> list[str]:
    """The saved profile names, sorted."""
    return sorted(path.stem for path in directory.glob("*.yaml") if _NAME.fullmatch(path.stem))


def normalize(filters) -> dict:
    """A clean copy of `filters`, with defaults filled in; raises `ProfileError` for anything else."""
    if not isinstance(filters, dict):
        raise ProfileError("filters must be a mapping")
    human = filters.get("human_label", "any")
    verdict = filters.get("classifier", "any")
    if human not in HUMAN_LABELS:
        raise ProfileError(f"human_label must be one of {', '.join(HUMAN_LABELS)}")
    if verdict not in CLASSIFIER_VERDICTS:
        raise ProfileError(f"classifier must be one of {', '.join(CLASSIFIER_VERDICTS)}")
    ranges = {}
    raw = filters.get("ranges")
    raw = {} if raw is None else raw
    if not isinstance(raw, dict):
        raise ProfileError("ranges must be a mapping of criterion name to {min, max}")
    for criterion, bounds in raw.items():
        if not isinstance(criterion, str) or not isinstance(bounds, dict) or not set(bounds) <= {"min", "max"}:
            raise ProfileError(f"the range of {criterion!r} must be a mapping with min and/or max")
        clean = {}
        for key, value in bounds.items():
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ProfileError(f"{criterion} {key} must be a finite number")
            clean[key] = float(value)
        if clean:
            ranges[criterion] = clean
    inverted = filters.get("invert")
    inverted = [] if inverted is None else inverted
    if not isinstance(inverted, list) or not all(isinstance(name, str) for name in inverted):
        raise ProfileError("invert must be a list of filter names")
    return {"human_label": human, "classifier": verdict, "ranges": ranges, "invert": sorted(set(inverted))}


def save(name: str, filters, directory: Path = PROFILES_DIR) -> Path:
    """Write the profile, replacing one with the same name, and return its path."""
    import yaml

    path = profile_path(name, directory)
    clean = normalize(filters)
    if not clean["invert"]:
        del clean["invert"]  # keep the file to what is set
    document = {"schema": SCHEMA, "name": name, "filters": clean}
    directory.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".yaml.tmp")
    temp.write_text(yaml.safe_dump(document, sort_keys=False, default_flow_style=False), encoding="utf-8")
    temp.replace(path)
    return path


def load(name: str, directory: Path = PROFILES_DIR) -> dict:
    """The profile's filters; `ProfileNotFound` when there is no such profile."""
    import yaml

    path = profile_path(name, directory)
    if not path.is_file():
        raise ProfileNotFound(f"no profile named {name!r}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if data.get("schema") != SCHEMA:
        raise ProfileError(f"{path}: unsupported schema {data.get('schema')!r}")
    return normalize(data.get("filters"))
