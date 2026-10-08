import numpy as np
import pytest

yaml = pytest.importorskip("yaml")

from tools.scene_analysis import store as store_module
from tools.scene_analysis.populate import populate, production_condition, scene_stats
from tools.scene_analysis.store import SceneStore, Status

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


def add(store, first=0, last=9, video="vid", fmt="160", stats=None):
    """Insert a scene that must succeed (201)."""
    response = store.insert_scene(video, fmt, first, last, first / 25, last / 25, last - first + 1, stats)
    assert response.status == Status.CREATED, response
    return response


def scene(store, first=0, video="vid", fmt="160"):
    response = store.get_scene(video, fmt, first)
    assert response.status == 200, response
    return response.data


def scenes(store, predicate=lambda s: True):
    return store.select_scenes(predicate).data


def test_insert_returns_201_then_duplicate_is_409_and_changes_nothing(store):
    assert store.insert_scene("vid", "160", 0, 9, 0, 0.4, 10, {"band": STATS}).status == 201
    before = store.path.read_text()
    again = store.insert_scene("vid", "160", 0, 9, 0, 0.4, 10, {"band": {**STATS, "max": 99.0}})
    assert again.status == Status.CONFLICT and not again.ok and "already exists" in again.message
    assert store.path.read_text() == before
    assert scene(store)["stats"]["band"]["max"] == 2.0


def test_an_overlapping_scene_is_409(store):
    add(store, 10, 19)
    for first, last in ((5, 10), (15, 25), (12, 14), (0, 30)):
        assert store.insert_scene("vid", "160", first, last, 0, 1, last - first + 1).status == 409
    assert len(scenes(store)) == 1


def test_invalid_scene_is_400_and_writes_nothing(store):
    assert store.insert_scene("vid", "160", 9, 0, 0, 1, 1).status == 400
    assert store.insert_scene("vid", "160", 0, 9, 0, 1, 10, {"band": {"op": ">"}}).status == 400
    assert not store.path.exists()


def test_the_file_is_a_tree_of_videos_formats_and_scenes(store):
    add(store, 10, 19, stats={"band": STATS})
    add(store, 0, 9)
    add(store, 0, 9, fmt="18")
    add(store, 0, 9, video="other")
    data = yaml.safe_load(store.path.read_text())
    assert [v["video_id"] for v in data["videos"]] == ["vid", "other"]
    assert [f["format_id"] for f in data["videos"][0]["formats"]] == ["160", "18"]
    in_file = data["videos"][0]["formats"][0]["scenes"]
    assert [s["first_frame"] for s in in_file] == [0, 10]  # kept in frame order
    assert in_file[1]["stats"]["band"]["max"] == 2.0 and in_file[1]["claude"] is None
    assert list(in_file[0]) == ["first_frame", "last_frame", "start_ts", "end_ts", "frame_count", "claude", "stats"]
    assert "video_id" not in in_file[0] and "scene_index" not in in_file[0] and "frame" not in in_file[0]


def test_returned_scenes_carry_their_video_and_format(store):
    add(store, 0, 9, video="other", fmt="18")
    got = scene(store, 0, "other", "18")
    assert (got["video_id"], got["format_id"], got["first_frame"], got["last_frame"]) == ("other", "18", 0, 9)


def test_same_frames_in_another_video_or_format_are_different_scenes(store):
    add(store)
    add(store, video="other")
    add(store, fmt="18")
    assert len(scenes(store)) == 3


def test_numpy_values_are_stored_as_plain_numbers_and_round_trip(store):
    add(store, stats={"band": {**STATS, "max": np.float32(2.5), "threshold": np.float64(180)}})
    assert "!!python" not in store.path.read_text()
    assert scene(SceneStore(store.path))["stats"]["band"]["max"] == 2.5


def test_set_criterion_stats_returns_201_new_200_replaced_204_unchanged(store):
    add(store, stats={"band": STATS})
    assert store.set_criterion_stats("vid", "160", 0, "texture", {**STATS, "op": "<"}).status == 201
    assert store.set_criterion_stats("vid", "160", 0, "band", {**STATS, "max": 7.0}).status == 200
    mtime = store.path.stat().st_mtime_ns
    same = store.set_criterion_stats("vid", "160", 0, "band", {**STATS, "max": 7.0})
    assert same.status == Status.NO_CONTENT and same.ok
    assert store.path.stat().st_mtime_ns == mtime  # nothing was written
    got = scene(store)
    assert set(got["stats"]) == {"band", "texture"} and got["stats"]["band"]["max"] == 7.0


def test_set_criterion_stats_errors(store):
    add(store, stats={"band": STATS})
    assert store.set_criterion_stats("vid", "160", 5, "band", STATS).status == 404  # no scene *starts* at 5
    assert store.set_criterion_stats("vid", "18", 0, "band", STATS).status == 404
    assert store.set_criterion_stats("vid", "160", 0, "band", {"op": ">"}).status == 400


def test_find_scene_by_frame_locator(store):
    add(store, 0, 9)
    add(store, 10, 19)
    found = lambda *a: store.find_scene(*a)
    assert found("vid", "160", 0).data["first_frame"] == 0
    assert found("vid", "160", 9).data["first_frame"] == 0
    assert found("vid", "160", 10).data["first_frame"] == 10
    for args in (("vid", "160", 20), ("vid", "18", 5), ("nope", "160", 5)):
        assert found(*args).status == 404
    assert store.get_scene("vid", "160", 3).status == 404  # get_scene wants the first frame


def test_claude_status_201_200_204_by_frame(store):
    add(store, 0, 9)
    add(store, 10, 19)
    assert scene(store, 10)["claude"] is None
    assert store.set_claude_status("vid", "160", 12, "meme", "glitch card", "miss").status == 201
    assert scene(store, 0)["claude"] is None
    claude = scene(store, 10)["claude"]
    assert (claude["verdict"], claude["reason"], claude["check"]) == ("meme", "glitch card", "miss")
    assert claude["checked_at"]
    assert store.set_claude_status("vid", "160", 19, "meme", "glitch card", "miss").status == 204
    assert scene(store, 10)["claude"] == claude  # untouched, checked_at included
    assert store.set_claude_status("vid", "160", 19, "not_meme", "plain shot", "false_positive").status == 200
    assert scene(store, 10)["claude"]["verdict"] == "not_meme"
    assert store.set_claude_status("vid", "160", 12, "maybe").status == 400
    assert store.set_claude_status("vid", "160", 12, "meme", check="x").status == 400
    assert store.set_claude_status("vid", "160", 99, "meme").status == 404


def test_select_scenes_returns_copies(store):
    add(store, 0, 9)
    add(store, 10, 19)
    assert [s["first_frame"] for s in scenes(store, lambda s: s["first_frame"] > 5)] == [10]
    scenes(store)[0]["last_frame"] = 123
    assert scene(store)["last_frame"] == 9


def test_a_corrupt_or_foreign_file_is_500_and_untouched(store):
    store.path.parent.mkdir(parents=True)
    bad = ("videos: [", "- just\n- a list\n", "version: 2\nvideos:\n- video_id: x\n",
           "version: 1\nscenes: []\n",  # the old flat layout
           "version: 2\nvideos:\n- video_id: x\n  formats:\n  - format_id: '1'\n    scenes:\n"
           "    - {first_frame: 0, last_frame: 9, start_ts: 0, end_ts: 1, frame_count: 10, stats: {}, claude: null}\n"
           "    - {first_frame: 5, last_frame: 12, start_ts: 0, end_ts: 1, frame_count: 8, stats: {}, claude: null}\n")
    for text in bad:
        store.path.write_text(text)
        assert store.insert_scene("vid", "160", 0, 9, 0, 1, 10).status == Status.SERVER_ERROR
        assert store.select_scenes().status == 500
        assert store.set_claude_status("vid", "160", 0, "meme").status == 500
        assert store.path.read_text() == text


def test_a_failed_write_leaves_the_old_file_and_no_temp_files(store, monkeypatch):
    add(store)
    before = store.path.read_text()

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(store_module.os, "replace", boom)
    with pytest.raises(OSError):
        store.insert_scene("vid", "160", 10, 19, 0, 1, 10)
    assert store.path.read_text() == before
    assert not list(store.path.parent.glob("*.tmp"))


def test_the_previous_version_is_kept_as_a_backup(store):
    add(store, 0, 9)
    first = store.path.read_text()
    add(store, 10, 19)
    assert store.path.with_name("scenes.yaml.bak").read_text() == first


def test_batch_writes_once_and_rolls_back_on_error(store, monkeypatch):
    writes = []
    real = store._save
    monkeypatch.setattr(store, "_save", lambda videos: (writes.append(1), real(videos)))
    with store.batch():
        add(store, 0, 9)
        add(store, 10, 19)
        assert len(scenes(store)) == 2
    assert len(writes) == 1
    with pytest.raises(RuntimeError):
        with store.batch():
            add(store, 20, 29)
            raise RuntimeError("stop")
    assert [s["first_frame"] for s in scenes(store)] == [0, 10]


def test_scene_stats():
    stats = scene_stats(np.array([100.0, 200.0, 300.0, 100.0]), (">", 180))
    assert stats == {"op": ">", "threshold": 180.0, "min": 100.0, "max": 300.0, "mean": 175.0,
                     "std": pytest.approx(np.std([100, 200, 300, 100])), "share_flagged": 0.5}
    single = scene_stats(np.array([5.0]), ("<", 10))
    assert single["std"] == 0 and single["share_flagged"] == 1
    with pytest.raises(ValueError):
        scene_stats(np.array([1.0]), ("==", 1))


def test_scene_stats_without_a_condition_have_no_share(store):
    stats = scene_stats(np.array([1.0, 3.0]), None)
    assert (stats["op"], stats["threshold"], stats["share_flagged"]) == (None, None, None)
    assert (stats["min"], stats["max"], stats["mean"], stats["std"]) == (1.0, 3.0, 2.0, 1.0)
    add(store, stats={"edge": stats})
    assert scene(store)["stats"]["edge"]["op"] is None


def test_production_condition():
    assert production_condition({"band": [{"op": ">", "value": 180}]}, "band") == (">", 180.0)
    assert production_condition({}, "band") is None


def run(store, band, other, offset=0):
    pts = np.arange(30) / 25
    return populate(store, "vid", "160", pts, np.array([0, 10, 20]), np.array([9, 19, 29]),
                    {"band": band + offset, "edge": other}, {"band": (">", 180.0), "edge": None})


def test_populate_stores_every_criterion_is_idempotent_and_keeps_claude(store):
    band = np.concatenate([np.full(10, 50.0), np.full(10, 170.0), np.full(10, 200.0)])
    other = np.arange(30, dtype=float)
    first = run(store, band, other)
    assert (first.inserted, first.updated, first.unchanged, first.errors) == (3, 0, 0, [])
    assert store.set_claude_status("vid", "160", 15, "meme", "x", "miss").status == 201
    again = run(store, band, other)  # identical data: nothing changes
    assert (again.inserted, again.updated, again.unchanged, again.errors) == (0, 0, 3, [])
    second = run(store, band, other, offset=5)
    assert (second.inserted, second.updated, second.unchanged, second.errors) == (0, 3, 0, [])
    got = scenes(store)
    assert len(got) == 3 and all(set(s["stats"]) == {"band", "edge"} for s in got)
    assert got[1]["claude"]["verdict"] == "meme"
    assert got[1]["stats"]["band"]["max"] == 175.0 and got[1]["stats"]["band"]["share_flagged"] == 0
    assert got[2]["stats"]["band"]["share_flagged"] == 1
    assert got[1]["stats"]["edge"]["min"] == 10.0 and got[1]["stats"]["edge"]["share_flagged"] is None
    assert (got[1]["first_frame"], got[1]["last_frame"], got[1]["frame_count"]) == (10, 19, 10)
    assert got[1]["start_ts"] == pytest.approx(0.4) and got[1]["end_ts"] == pytest.approx(0.76)


def test_populate_a_later_criterion_adds_to_existing_scenes(store):
    pts = np.arange(30) / 25
    args = (store, "vid", "160", pts, np.array([0, 10, 20]), np.array([9, 19, 29]))
    assert populate(*args, {"band": np.zeros(30)}, {"band": (">", 180.0)}).inserted == 3
    result = populate(*args, {"edge": np.arange(30.0)}, {"edge": None})
    assert (result.inserted, result.updated, result.unchanged) == (0, 3, 0)
    assert all(set(s["stats"]) == {"band", "edge"} for s in scenes(store))


def test_populate_reports_non_finite_scores_and_stores_the_rest(store):
    band = np.full(30, 100.0)
    other = np.arange(30, dtype=float)
    other[12] = np.nan
    result = run(store, band, other)
    assert result.inserted == 3 and len(result.errors) == 1 and "scene 1" in result.errors[0] and "edge" in result.errors[0]
    got = scenes(store)
    assert set(got[1]["stats"]) == {"band"} and set(got[0]["stats"]) == {"band", "edge"}


def test_populate_reports_an_unreadable_database_as_errors(store):
    store.path.parent.mkdir(parents=True)
    store.path.write_text("videos: [")
    with pytest.raises(store_module.SceneStoreError):  # batch() itself can't open the file
        run(store, np.zeros(30), np.zeros(30))


# --- Format choice ---------------------------------------------------------------------------------

from tools.scene_analysis import formats as formats_module  # noqa: E402
from tools.labeling.dataset import DatasetError  # noqa: E402

FORMATS = [
    {"format_id": "160", "ext": "mp4", "vcodec": "avc1.4d400c", "width": 256, "height": 144, "fps": 25, "size": 1e6, "av1": False},
    {"format_id": "133", "ext": "mp4", "vcodec": "avc1.4d4015", "width": 426, "height": 240, "fps": 25, "size": 2e6, "av1": False},
    {"format_id": "134", "ext": "mp4", "vcodec": "avc1.4d401e", "width": 640, "height": 360, "fps": 25, "size": 4e6, "av1": False},
]


def pick(tmp_path, answers, have=()):
    for fid in have:
        (tmp_path / f"vid_{fid}.mp4").write_bytes(b"x")
    shown, replies = [], iter(answers)
    chosen = formats_module.choose_format("vid", FORMATS, tmp_path, ask=lambda prompt: next(replies), show=shown.append, color=False)
    return chosen, shown


def test_enter_takes_the_labelers_default_when_nothing_is_downloaded(tmp_path):
    chosen, shown = pick(tmp_path, [""])
    assert chosen == "160"
    assert [l for l in shown if "(default)" in l] == [l for l in shown if "160" in l and "►" in l]
    assert not any("downloaded" in l for l in shown)


def test_downloaded_formats_are_marked_and_enter_takes_one_of_them(tmp_path):
    chosen, shown = pick(tmp_path, [""], have=["134"])
    assert chosen == "134"
    marked = [l for l in shown if "downloaded" in l]
    assert len(marked) == 1 and "134" in marked[0] and "default" in marked[0]


def test_among_several_downloaded_the_labelers_preference_is_the_default(tmp_path):
    chosen, _ = pick(tmp_path, [""], have=["134", "133"])
    assert chosen == "133"


def test_a_number_or_an_id_picks_and_a_bad_answer_asks_again(tmp_path):
    assert pick(tmp_path, ["3"])[0] == "134"
    assert pick(tmp_path, ["133"])[0] == "133"
    chosen, shown = pick(tmp_path, ["9", "abc", "2"])
    assert chosen == "133" and sum("Not a format" in l for l in shown) == 2


def test_colors_highlight_downloaded_else_default(tmp_path):
    (tmp_path / "vid_134.mp4").write_bytes(b"x")
    lines = formats_module.render(FORMATS, {"134"}, "134", color=True)
    assert lines[2].startswith("\033[1;32m") and lines[0].startswith("\033[2m")
    lines = formats_module.render(FORMATS, set(), "160", color=True)
    assert lines[0].startswith("\033[1;36m") and lines[1].startswith("\033[2m")


def test_no_formats_is_an_error(tmp_path):
    with pytest.raises(DatasetError):
        formats_module.choose_format("vid", [], tmp_path, ask=lambda p: "", show=lambda s: None)


def drive(keys, default="160", height=10, downloaded=()):
    stream, out = iter(keys), []
    result = formats_module.menu(FORMATS, set(downloaded), default, lambda: next(stream), out.append, height, color=False)
    return result, "".join(out)


def test_menu_starts_on_the_default_and_enter_selects_it():
    assert drive(["enter"])[0] == "160"
    assert drive(["enter"], default="133")[0] == "133"


def test_menu_arrows_move_and_stop_at_the_ends():
    assert drive(["down", "down", "enter"])[0] == "134"
    assert drive(["down", "down", "down", "down", "enter"])[0] == "134"
    assert drive(["up", "up", "enter"], default="134")[0] == "160"
    assert drive(["up", "enter"])[0] == "160"
    assert drive(["end", "enter"])[0] == "134" and drive(["end", "home", "enter"])[0] == "160"


def test_menu_cancel_returns_none():
    assert drive(["down", "cancel"])[0] is None


def test_menu_scrolls_within_its_height_and_pages():
    result, text = drive(["pagedown", "enter"], height=2)
    assert result == "134"
    assert "id 134" not in text.split("\033[")[0]  # the first screen shows only two formats
    assert drive(["pagedown", "pagedown", "pageup", "enter"], height=2)[0] == "160"


def test_read_key_parses_escape_sequences():
    import os
    for raw, name in ((b"\x1b[A", "up"), (b"\x1b[B", "down"), (b"\x1b[6~", "pagedown"), (b"\r", "enter"),
                      (b"j", "down"), (b"\x1b", "cancel"), (b"x", "")):
        r, w = os.pipe()
        os.write(w, raw)
        assert formats_module.read_key(r, wait=0.01) == name
        os.close(r), os.close(w)
