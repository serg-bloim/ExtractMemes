import pytest

pytest.importorskip("flask")
pytest.importorskip("yaml")

from tools.scene_analysis import store as store_module
from tools.scene_analysis.browser import create_app, query, thumb_path
from tools.scene_analysis.store import SceneStore


@pytest.fixture(autouse=True)
def real_database_untouched():
    def state():
        return {p: p.stat().st_mtime_ns for p in store_module.DEFAULT_PATH.parent.glob(store_module.DEFAULT_PATH.name + "*")}
    before = state()
    yield
    assert state() == before, "a test touched the real scene database"


def stats(lo, hi, share, threshold=2.1):
    return {"op": "<", "threshold": threshold, "min": lo, "max": hi, "mean": (lo + hi) / 2, "std": 0.1, "share_flagged": share}


@pytest.fixture
def store(tmp_path):
    db = SceneStore(tmp_path / "db" / "scenes.yaml")
    rows = [("a", "160", 0, 9, stats(5.0, 6.0, 0.0)), ("a", "160", 10, 19, stats(1.0, 3.0, 0.5)),
            ("a", "160", 20, 29, stats(0.2, 0.5, 1.0)), ("b", "269", 0, 4, stats(2.3, 3.0, 0.0))]
    for video, fmt, first, last, st in rows:
        assert db.insert_scene(video, fmt, first, last, first / 25, (last + 1) / 25, last - first + 1, {"edge_histogram": st}).status == 201
    db.set_claude_status("a", "160", 10, "not_meme", "plain footage", "false_positive")
    db.set_claude_status("b", "269", 0, "meme", "static around a card", "miss")
    return db


def scenes(store):
    return store.snapshot().data


def firsts(result):
    return [(r["video_id"], r["first_frame"]) for r in result["rows"]]


def test_default_order_and_totals(store):
    result = query(scenes(store), {})
    assert result["total"] == 4 and firsts(result) == [("a", 0), ("a", 10), ("a", 20), ("b", 0)]
    assert result["criterion"] == "edge_histogram" and result["summary"] == {"checked": 2, "meme": 1, "not_meme": 1, "unsure": 0}
    assert result["videos"] == [{"video_id": "a", "formats": ["160"]}, {"video_id": "b", "formats": ["269"]}]


def test_sort_by_stat_and_distance_with_missing_last(store):
    result = query(scenes(store), {"sort": "distance"})
    assert firsts(result) == [("a", 10), ("b", 0), ("a", 20), ("a", 0)]
    assert [r["stats"]["distance"] for r in result["rows"]] == [0.0, pytest.approx(0.2), pytest.approx(1.6), pytest.approx(2.9)]
    desc = query(scenes(store), {"sort": "max", "dir": "desc"})
    assert [r["stats"]["max"] for r in desc["rows"]] == [6.0, 3.0, 3.0, 0.5]
    by_verdict = query(scenes(store), {"sort": "verdict"})
    assert [r["claude"] is not None for r in by_verdict["rows"]] == [True, True, False, False]  # unchecked scenes last
    assert query(scenes(store), {"sort": "verdict", "dir": "desc"})["rows"][-1]["claude"] is None


def test_filters(store):
    data = scenes(store)
    assert firsts(query(data, {"video": "b"})) == [("b", 0)]
    assert firsts(query(data, {"format": "160", "claude": "none"})) == [("a", 0), ("a", 20)]
    assert firsts(query(data, {"claude": "meme"})) == [("b", 0)]
    assert firsts(query(data, {"claude": "checked", "check": "false_positive"})) == [("a", 10)]
    assert firsts(query(data, {"flagged": "mixed"})) == [("a", 10)]
    assert firsts(query(data, {"flagged": "all"})) == [("a", 20)]
    assert firsts(query(data, {"flagged": "none"})) == [("a", 0), ("b", 0)]
    assert firsts(query(data, {"q": "STATIC"})) == [("b", 0)]


def test_paging_clamps_and_ignores_bad_values(store):
    data = scenes(store)
    assert query(data, {"size": "25", "page": "9"})["page"] == 1
    assert query(data, {"size": "nope", "page": "x"})["size"] == 50
    assert query(data, {"sort": "not-a-key"})["total"] == 4


def test_thumb_path_only_when_cached(tmp_path):
    thumbs = tmp_path / "a_160" / "thumbs"
    thumbs.mkdir(parents=True)
    assert thumb_path(tmp_path, "a", "160", 10, 19) is None
    (thumbs / "14.jpg").write_bytes(b"jpg")
    assert thumb_path(tmp_path, "a", "160", 10, 19) == thumbs / "14.jpg"
    assert thumb_path(tmp_path, "../a", "160", 10, 19) is None


def test_http_endpoints_and_placeholder_flag(store, tmp_path):
    cache = tmp_path / "cache"
    (cache / "a_160" / "thumbs").mkdir(parents=True)
    (cache / "a_160" / "thumbs" / "14.jpg").write_bytes(b"jpegdata")
    client = create_app(store, cache).test_client()
    assert client.get("/").status_code == 200
    rows = client.get("/api/scenes?sort=first_frame&video=a").get_json()["rows"]
    assert [(r["first_frame"], r["has_thumb"]) for r in rows] == [(0, False), (10, True), (20, False)]
    assert client.get("/thumb/a/160/10/19.jpg").data == b"jpegdata"
    assert client.get("/thumb/a/160/0/9.jpg").status_code == 404
    detail = client.get("/api/scene?video=a&format=160&first=10").get_json()
    assert detail["claude"]["verdict"] == "not_meme" and detail["has_thumb"] is True and "edge_histogram" in detail["stats"]
    assert client.get("/api/scene?video=a&format=160&first=11").status_code == 404
    assert client.get("/", headers={"Host": "evil.example.com"}).status_code == 403


def test_picks_up_a_changed_file_and_does_not_write(store, tmp_path):
    client = create_app(store, tmp_path).test_client()
    before = store.path.read_bytes()
    assert client.get("/api/scenes").get_json()["total"] == 4
    store.insert_scene("c", "160", 0, 9, 0, 0.4, 10, {"edge_histogram": stats(1.0, 1.5, 1.0)})
    assert client.get("/api/scenes").get_json()["total"] == 5
    assert store.path.read_bytes() != before and not list(store.path.parent.glob("*.tmp"))


def test_snapshot_does_not_wait_for_an_open_session(store):
    import threading

    other = SceneStore(store.path)
    with other.batch():
        other.set_claude_status("a", "160", 0, "meme", "x", "miss")  # unsaved, lock held
        result = {}
        thread = threading.Thread(target=lambda: result.update(r=store.snapshot()))
        thread.start()
        thread.join(5)
        assert not thread.is_alive(), "snapshot waited for the writer's lock"
    assert next(s for s in result["r"].data if s["first_frame"] == 0 and s["video_id"] == "a")["claude"] is None
