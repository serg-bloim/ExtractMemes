import json

import numpy as np
import pytest

from extract_memes import criteria
from extract_memes.criteria import Criterion, criterion, edge_histogram as eh


def frame_with_edges(value: int) -> np.ndarray:
    frame = np.full((144, 256, 3), 128, dtype=np.uint8)
    frame[:, :13] = value
    frame[:, -13:] = value
    return frame


def test_features_are_a_normalised_16_bin_histogram_of_the_edges_only():
    histogram = eh.features(frame_with_edges(0))

    assert histogram.shape == (16,) and histogram.sum() == pytest.approx(1)
    assert histogram[0] == 1  # the grey middle (128) is not counted
    assert eh.features(frame_with_edges(255))[15] == 1
    half = frame_with_edges(0)
    half[:, -13:] = 200
    assert eh.features(half)[0] == pytest.approx(0.5) and eh.features(half)[200 // 16] == pytest.approx(0.5)


def test_the_distance_is_zero_at_the_mean_and_grows_in_units_of_the_per_bin_spread():
    mean = np.full(16, 1 / 16)
    narrow, wide = np.full(16, 0.01), np.full(16, 0.04)
    shifted = mean + 0.02

    assert eh.distance(mean, mean, narrow) == 0
    assert eh.distance(shifted, mean, narrow) == pytest.approx(2, rel=0.02)
    assert eh.distance(shifted, mean, wide) == pytest.approx(0.5, rel=0.02)
    assert eh.distance(mean + 0.04, mean, narrow) > eh.distance(shifted, mean, narrow)


def test_the_shipped_reference_tells_a_card_like_edge_from_ordinary_edges():
    mean, _ = eh.reference()
    card_like = np.random.default_rng(0).choice(256, size=(144, 26), p=_p(mean)).astype(np.uint8)
    frame = np.full((144, 256, 3), 128, dtype=np.uint8)
    frame[:, :13] = card_like[:, :13, None]
    frame[:, -13:] = card_like[:, 13:, None]

    assert criteria.get("edge_histogram").score(frame) < 3 < criteria.get("edge_histogram").score(frame_with_edges(128))


def _p(mean):
    weights = np.repeat(mean / 16, 16)
    return weights / weights.sum()


def test_a_missing_or_malformed_reference_names_the_file_and_the_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(eh, "DATA_DIR", tmp_path)
    with pytest.raises(RuntimeError, match=r"Missing reference .*edge_histogram\.json.*build_template"):
        eh.reference()
    (tmp_path / eh.REFERENCE_FILE).write_text(json.dumps({"mean": [1, 2], "std": [1, 2]}))
    with pytest.raises(RuntimeError, match=r"Malformed reference .*build_template"):
        eh.reference()
    (tmp_path / eh.REFERENCE_FILE).write_text("{not json")
    with pytest.raises(RuntimeError, match="Malformed reference"):
        eh.reference()


def test_the_reference_is_read_again_when_the_file_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(eh, "DATA_DIR", tmp_path)
    path = tmp_path / eh.REFERENCE_FILE
    path.write_text(json.dumps({"mean": [0.1] * 16, "std": [0.2] * 16}))
    assert eh.reference()[0][0] == 0.1
    path.write_text(json.dumps({"mean": [0.3] * 16, "std": [0.2] * 16}))
    import os
    os.utime(path, ns=(1, path.stat().st_mtime_ns + 10**9))
    assert eh.reference()[0][0] == 0.3


def test_importing_the_criterion_reads_no_file(monkeypatch, tmp_path):
    monkeypatch.setattr(eh, "DATA_DIR", tmp_path)  # nothing there; registering and listing must still work
    assert "edge_histogram" in criteria.all_criteria()


def test_a_data_file_is_part_of_the_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setattr(criteria, "DATA_DIR", tmp_path)
    monkeypatch.setattr(criteria, "_REGISTRY", dict(criteria._REGISTRY))

    @criterion("needs_data", data=("ref.json",))
    def needs_data(frame):
        return 0.0

    no_file = criteria.get("needs_data").fingerprint()
    (tmp_path / "ref.json").write_text("1")
    one = criteria.get("needs_data").fingerprint()
    (tmp_path / "ref.json").write_text("2")
    two = criteria.get("needs_data").fingerprint()

    assert len({no_file, one, two}) == 3
    assert criteria.get("band").data == () and Criterion("x", lambda f: 0.0, module=None).data == ()
