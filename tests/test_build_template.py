import json

import numpy as np
import pytest

pytest.importorskip("yaml")

from tools.evaluation import build_template as bt


def test_summarize_gives_the_mean_and_spread_per_bin_and_the_sources():
    rows = np.array([[0.2, 0.8], [0.4, 0.6]])

    content = bt.summarize(rows, ["b", "a"])

    assert content == {"frames": 2, "videos": ["a", "b"], "mean": [0.3, 0.7], "std": [0.1, 0.1]}


def test_the_template_builder_knows_the_edge_histogram_and_its_file_name():
    module, file_name = bt.TEMPLATES["edge_histogram"]

    assert file_name == "edge_histogram.json" and callable(module.features)


def test_the_shipped_reference_matches_the_feature_size():
    from extract_memes.criteria import DATA_DIR

    data = json.loads((DATA_DIR / "edge_histogram.json").read_text())

    assert len(data["mean"]) == len(data["std"]) == 16 and data["frames"] > 0 and data["videos"]
