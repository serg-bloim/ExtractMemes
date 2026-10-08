import numpy as np
import pytest

pytest.importorskip("yaml")

from tools.scene_analysis import store as store_module
from tools.scene_analysis.populate import populate, production_condition, scene_stats
from tools.scene_analysis.store import SceneExistsError, SceneNotFoundError, SceneStore, SceneStoreError

STATS = {"op": ">", "threshold": 180.0, "min": 1.0, "max": 2.0, "mean": 1.5, "std": 0.5, "share_flagged": 0.0}


@pytest.fixture(autouse=True)
def real_database_untouched():
    """Tests use temp databases only; fail if the real file (or its sidecars) appears or changes."""
    def state():
        return {p: p.stat().st_mtime_ns for p in store_module.DEFAULT_PATH.parent.glob(store_module.DEFAULT_PATH.name + "*")}
    before = state()
    yield
    assert state() == before, "a test touched the real scene database"


@pytest.fixture
def store(tmp_path):
    return SceneStore(tmp_path / "db" / "scenes.yaml")


def add(store, index=0, first=0, last=9, video="vid", fmt="160", stats=None):
    store.insert_scene(video, fmt, index, first, last, first / 25, last / 25, last - first + 1, stats)


def test_insert_then_duplicate_is_an_error_and_changes_nothing(store):
    add(store, stats={"band": STATS})
    before = store.path.read_text()
    with pytest.raises(SceneExistsError):
        add(store, stats={"band": {**STATS, "max": 99.0}})
    assert store.path.read_text() == before
    assert store.get_scene("vid", "160", 0)["stats"]["band"]["max"] == 2.0


def test_same_index_in_another_video_or_format_is_a_different_scene(store):
    add(store)
    add(store, video="other")
    add(store, fmt="18")
    assert len(store.select_scenes()) == 3


def test_numpy_values_are_stored_as_plain_numbers_and_round_trip(store):
    add(store, stats={"band": {**STATS, "max": np.float32(2.5), "threshold": np.float64(180)}})
    assert "!!python" not in store.path.read_text()
    assert SceneStore(store.path).get_scene("vid", "160", 0)["stats"]["band"]["max"] == 2.5


def test_set_criterion_stats_adds_and_replaces(store):
    add(store, stats={"band": STATS})
    store.set_criterion_stats("vid", "160", 0, "texture", {**STATS, "op": "<"})
    store.set_criterion_stats("vid", "160", 0, "band", {**STATS, "max": 7.0})
    scene = store.get_scene("vid", "160", 0)
    assert set(scene["stats"]) == {"band", "texture"} and scene["stats"]["band"]["max"] == 7.0
    with pytest.raises(SceneNotFoundError):
        store.set_criterion_stats("vid", "160", 5, "band", STATS)


def test_invalid_stats_are_refused(store):
    with pytest.raises(SceneStoreError):
        add(store, stats={"band": {"op": ">"}})
    assert not store.path.exists()


def test_find_scene_by_frame_locator(store):
    add(store, 0, 0, 9)
    add(store, 1, 10, 19)
    assert store.find_scene("vid", "160", 0)["scene_index"] == 0
    assert store.find_scene("vid", "160", 9)["scene_index"] == 0
    assert store.find_scene("vid", "160", 10)["scene_index"] == 1
    for args in (("vid", "160", 20), ("vid", "18", 5), ("nope", "160", 5)):
        with pytest.raises(SceneNotFoundError):
            store.find_scene(*args)


def test_claude_status_by_frame_set_and_replace(store):
    add(store, 0, 0, 9)
    add(store, 1, 10, 19)
    assert store.get_scene("vid", "160", 1)["claude"] is None
    store.set_claude_status("vid", "160", 12, "meme", "glitch card", "miss")
    assert store.get_scene("vid", "160", 0)["claude"] is None
    claude = store.get_scene("vid", "160", 1)["claude"]
    assert (claude["verdict"], claude["reason"], claude["check"]) == ("meme", "glitch card", "miss")
    assert claude["checked_at"]
    store.set_claude_status("vid", "160", 19, "not_meme", "plain shot", "false_positive")
    assert store.get_scene("vid", "160", 1)["claude"]["verdict"] == "not_meme"
    with pytest.raises(SceneStoreError):
        store.set_claude_status("vid", "160", 12, "maybe")
    with pytest.raises(SceneNotFoundError):
        store.set_claude_status("vid", "160", 99, "meme")


def test_select_scenes_returns_copies(store):
    add(store, 0, 0, 9)
    add(store, 1, 10, 19)
    assert [s["scene_index"] for s in store.select_scenes(lambda s: s["first_frame"] > 5)] == [1]
    store.select_scenes()[0]["first_frame"] = 123
    assert store.get_scene("vid", "160", 0)["first_frame"] == 0


def test_a_corrupt_or_foreign_file_is_refused_and_untouched(store):
    store.path.parent.mkdir(parents=True)
    for text in ("scenes: [", "- just\n- a list\n", "version: 1\nscenes:\n- video_id: x\n"):
        store.path.write_text(text)
        with pytest.raises(SceneStoreError):
            add(store)
        with pytest.raises(SceneStoreError):
            store.select_scenes()
        assert store.path.read_text() == text


def test_a_failed_write_leaves_the_old_file_and_no_temp_files(store, monkeypatch):
    add(store)
    before = store.path.read_text()

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(store_module.os, "replace", boom)
    with pytest.raises(OSError):
        add(store, 1, 10, 19)
    assert store.path.read_text() == before
    assert not list(store.path.parent.glob("*.tmp"))


def test_the_previous_version_is_kept_as_a_backup(store):
    add(store, 0, 0, 9)
    first = store.path.read_text()
    add(store, 1, 10, 19)
    assert store.path.with_name("scenes.yaml.bak").read_text() == first


def test_batch_writes_once_and_rolls_back_on_error(store, monkeypatch):
    writes = []
    real = store._save
    monkeypatch.setattr(store, "_save", lambda scenes: (writes.append(1), real(scenes)))
    with store.batch():
        add(store, 0, 0, 9)
        add(store, 1, 10, 19)
        assert len(store.select_scenes()) == 2
    assert len(writes) == 1
    with pytest.raises(RuntimeError):
        with store.batch():
            add(store, 2, 20, 29)
            raise RuntimeError("stop")
    assert [s["scene_index"] for s in store.select_scenes()] == [0, 1]


def test_scene_stats():
    stats = scene_stats(np.array([100.0, 200.0, 300.0, 100.0]), ">", 180)
    assert stats == {"op": ">", "threshold": 180.0, "min": 100.0, "max": 300.0, "mean": 175.0,
                     "std": pytest.approx(np.std([100, 200, 300, 100])), "share_flagged": 0.5}
    assert scene_stats(np.array([5.0]), "<", 10)["std"] == 0 and scene_stats(np.array([5.0]), "<", 10)["share_flagged"] == 1
    with pytest.raises(ValueError):
        scene_stats(np.array([1.0]), "==", 1)


def test_production_condition():
    assert production_condition({"band": [{"op": ">", "value": 180}]}, "band") == (">", 180.0)
    assert production_condition({}, "band") is None


def test_populate_is_idempotent_keeps_claude_and_adds_criteria(store):
    pts = np.arange(30) / 25
    rows, row_last = np.array([0, 10, 20]), np.array([9, 19, 29])
    band = np.concatenate([np.full(10, 50.0), np.full(10, 170.0), np.full(10, 200.0)])
    assert populate(store, "vid", "160", pts, rows, row_last, band, "band", ">", 180) == (3, 0)
    store.set_claude_status("vid", "160", 15, "meme", "x", "miss")
    assert populate(store, "vid", "160", pts, rows, row_last, band + 5, "band", ">", 180) == (0, 3)
    assert populate(store, "vid", "160", pts, rows, row_last, band, "texture", "<", 60) == (0, 3)
    scenes = store.select_scenes()
    assert len(scenes) == 3
    assert scenes[1]["claude"]["verdict"] == "meme"
    assert scenes[1]["stats"]["band"]["max"] == 175.0 and scenes[1]["stats"]["band"]["share_flagged"] == 0
    assert scenes[2]["stats"]["band"]["share_flagged"] == 1
    assert set(scenes[0]["stats"]) == {"band", "texture"}
    assert (scenes[1]["first_frame"], scenes[1]["last_frame"], scenes[1]["frame_count"]) == (10, 19, 10)
    assert scenes[1]["start_ts"] == pytest.approx(0.4) and scenes[1]["end_ts"] == pytest.approx(0.76)
