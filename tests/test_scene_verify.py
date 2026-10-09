import numpy as np
import pytest

pytest.importorskip("yaml")

from tools.scene_analysis import store as store_module
from tools.scene_analysis.store import SceneStore
from tools.scene_analysis.verify import (Judgement, check_of, distance_from_threshold, extreme_frames, parse_answers,
                                         select, verdict_of, verify)


def stats(lo, hi, share, threshold=2.1):
    return {"op": "<", "threshold": threshold, "min": lo, "max": hi, "mean": (lo + hi) / 2, "std": 0.1, "share_flagged": share}


@pytest.fixture(autouse=True)
def real_database_untouched():
    def state():
        return {p: p.stat().st_mtime_ns for p in store_module.DEFAULT_PATH.parent.glob(store_module.DEFAULT_PATH.name + "*")}
    before = state()
    yield
    assert state() == before, "a test touched the real scene database"


@pytest.fixture
def store(tmp_path):
    db = SceneStore(tmp_path / "db" / "scenes.yaml")
    # (first, stats): far unflagged, near unflagged, straddling, flagged just under, flagged far under
    for first, st in [(0, stats(5.0, 6.0, 0.0)), (10, stats(2.3, 3.0, 0.0)), (20, stats(1.0, 3.0, 0.5)),
                      (30, stats(1.5, 2.0, 1.0)), (40, stats(0.2, 0.5, 1.0))]:
        assert db.insert_scene("vid", "160", first, first + 9, first / 25, (first + 9) / 25, 10, {"edge_histogram": st}).status == 201
    return db


def firsts(scenes):
    return [s["first_frame"] for s in scenes]


def test_distance_is_zero_when_scores_straddle_the_threshold():
    assert distance_from_threshold(stats(1.0, 3.0, 0.5)) == 0
    assert distance_from_threshold(stats(2.1, 3.0, 0.0)) == 0
    assert distance_from_threshold(stats(2.5, 3.0, 0.0)) == pytest.approx(0.4)
    assert distance_from_threshold(stats(0.5, 1.5, 1.0)) == pytest.approx(0.6)


def test_select_ranks_by_distance_and_takes_top(store):
    assert firsts(select(store, "edge_histogram", 100)) == [20, 30, 10, 40, 0]
    assert firsts(select(store, "edge_histogram", 2)) == [20, 30]


def test_select_skips_checked_scenes_unless_recheck(store):
    store.set_claude_status("vid", "160", 20, "meme", "x", "false_positive")
    assert 20 not in firsts(select(store, "edge_histogram", 100))
    assert firsts(select(store, "edge_histogram", 100, recheck=True))[0] == 20


def test_select_ignores_scenes_without_a_condition(store):
    no_condition = {"op": None, "threshold": None, "min": 1.0, "max": 2.0, "mean": 1.5, "std": 0.1, "share_flagged": None}
    store.insert_scene("vid", "160", 50, 59, 2, 2.4, 10, {"edge_histogram": no_condition})
    store.insert_scene("vid", "160", 60, 69, 2.4, 2.8, 10, {})
    assert 50 not in firsts(select(store, "edge_histogram", 100)) and 60 not in firsts(select(store, "edge_histogram", 100))


def test_extreme_frames_are_min_and_max_within_the_scene():
    scores = np.array([0.0, 9.0, 3.0, 1.0, 7.0, 2.0, -5.0])
    assert extreme_frames(scores, 2, 5) == (3, 4)


def test_verdict_and_check_mapping():
    assert verdict_of(Judgement(True, True)) == "meme"
    assert verdict_of(Judgement(False, False)) == "not_meme"
    assert verdict_of(Judgement(True, False)) == "unsure"
    assert check_of(stats(2.2, 3.0, 0.0)) == "miss"
    assert check_of(stats(1.0, 3.0, 0.5)) == "false_positive"
    assert check_of(stats(1.0, 1.5, 1.0)) == "false_positive"


def test_parse_answers_by_scene_number():
    text = ('ok {"scenes": [{"scene": 2, "first": "NO", "second": "no", "reason": "b"}, '
            '{"scene": 1, "first": "yes", "second": "NO", "reason": "a"}, {"scene": 9, "first": "YES", "second": "YES"}, '
            '{"scene": 3, "first": "MAYBE", "second": "NO"}]}')
    assert parse_answers(text, 3) == [Judgement(True, False, "a"), Judgement(False, False, "b"), None]
    for bad in ("YES", '{"first": "YES"}', "{not json}", '{"scenes": 5}'):
        try:
            result = parse_answers(bad, 2)
        except ValueError:
            continue
        assert result == [None, None]


class FakeSource:
    def __init__(self, missing=()):
        self.missing = missing
        self.asked = []

    def scores(self, video, fmt, criterion):
        if (video, fmt) in self.missing:
            raise FileNotFoundError("not downloaded")
        return np.arange(100, dtype=float)[::-1]  # the lowest score of a scene is its last frame

    def frame(self, video, fmt, index):
        self.asked.append(index)
        return np.full((9, 16, 3), index, dtype=np.uint8)


def test_verify_stores_verdicts_with_check_and_frames(store):
    batches = []

    def judge(pairs):
        batches.append([(low.name, high.name) for low, high in pairs])
        return [Judgement(True, True, "card") for _ in pairs]

    result = verify(store, select(store, "edge_histogram", 100), "edge_histogram", FakeSource(), judge)
    assert result.checked == 5 and result.verdicts == {"meme": 5} and not result.errors
    assert batches == [[("scene1_low_frame_29.jpg", "scene1_high_frame_20.jpg"), ("scene2_low_frame_39.jpg", "scene2_high_frame_30.jpg"),
                        ("scene3_low_frame_19.jpg", "scene3_high_frame_10.jpg"), ("scene4_low_frame_49.jpg", "scene4_high_frame_40.jpg"),
                        ("scene5_low_frame_9.jpg", "scene5_high_frame_0.jpg")]]
    claude = store.get_scene("vid", "160", 10).data["claude"]
    assert claude["verdict"] == "meme" and claude["check"] == "miss" and "frame 19 YES, frame 10 YES" in claude["reason"]
    assert store.get_scene("vid", "160", 20).data["claude"]["check"] == "false_positive"


def test_scenes_are_split_into_batches_of_batch_size(store):
    sizes = []

    def judge(pairs):
        sizes.append(len(pairs))
        return [Judgement(False, False) for _ in pairs]

    result = verify(store, select(store, "edge_histogram", 100), "edge_histogram", FakeSource(), judge, batch_size=2)
    assert sizes == [2, 2, 1] and result.checked == 5


def test_unanswered_scene_and_failed_call_are_errors_that_do_not_stop_the_run(store):
    calls = []

    def judge(pairs):
        calls.append(len(pairs))
        if len(calls) == 1:
            return [Judgement(False, False, "no"), None]  # the second scene got no valid answer
        raise RuntimeError("claude failed")

    result = verify(store, select(store, "edge_histogram", 100), "edge_histogram", FakeSource(), judge, batch_size=2)
    assert result.checked == 1 and len(result.errors) == 1 + 2 + 1  # unanswered, a failed batch of two, a failed batch of one
    assert store.get_scene("vid", "160", 20).data["claude"]["verdict"] == "not_meme"
    assert store.get_scene("vid", "160", 30).data["claude"] is None
    assert sum("claude failed" in e for e in result.errors) == 3


def test_missing_video_is_an_error_and_calls_nothing(store):
    called = []
    result = verify(store, select(store, "edge_histogram", 100), "edge_histogram", FakeSource(missing={("vid", "160")}),
                    lambda pairs: called.append(1))
    assert result.checked == 0 and len(result.errors) == 5 and not called


def count_writes(store, monkeypatch, restore=True, **options):
    writes = []
    pristine = store.path.read_bytes()  # every count starts from the same database
    original = SceneStore._save
    monkeypatch.setattr(SceneStore, "_save", lambda self, videos: (writes.append(1), original(self, videos))[1])
    verify(store, select(store, "edge_histogram", 100), "edge_histogram", FakeSource(),
           lambda pairs: [Judgement(True, True) for _ in pairs], **options)
    if restore:
        store.path.write_bytes(pristine)
    return len(writes)


def test_save_every_n_batches(store, monkeypatch):
    assert count_writes(store, monkeypatch, batch_size=1, save_every=0) == 1  # only when the session closes
    assert count_writes(store, monkeypatch, batch_size=1, save_every=2) == 3  # after batches 2 and 4, and at the end
    assert count_writes(store, monkeypatch, batch_size=1, save_every=1) == 5  # after every batch (the last at the end)
    assert count_writes(store, monkeypatch, batch_size=1) == 1  # default: only when the session closes
    assert count_writes(store, monkeypatch, batch_size=5) == 1  # a single batch is written once


def test_whole_run_is_one_read_and_one_write(store, monkeypatch):
    assert count_writes(store, monkeypatch, restore=False, batch_size=2, save_every=0) == 1
    assert all(store.get_scene("vid", "160", f).data["claude"] for f in (0, 10, 20, 30, 40))


def test_ctrl_c_saves_what_was_judged_so_far(store):
    calls = []

    def judge(pairs):
        calls.append(1)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return [Judgement(True, True) for _ in pairs]

    result = verify(store, select(store, "edge_histogram", 100), "edge_histogram", FakeSource(), judge, batch_size=2)
    assert result.checked == 2 and "interrupted" in result.errors[-1]
    assert store.get_scene("vid", "160", 20).data["claude"] is not None
    assert store.get_scene("vid", "160", 10).data["claude"] is None


def test_timings_are_collected_per_stage(store):
    from tools.scene_analysis.verify import format_timings

    with store.batch():
        result = verify(store, select(store, "edge_histogram", 100), "edge_histogram", FakeSource(),
                        lambda pairs: [Judgement(True, True) for _ in pairs], batch_size=2)
    assert result.calls == 3 and set(result.timings) == {"frames", "claude", "verdicts"}
    assert all(seconds >= 0 for seconds in result.timings.values())
    assert store.timings["load"] > 0 and store.timings["save"] > 0
    report = format_timings(store.timings, 0.5, result, 10.0)
    for label in ("database load", "select scenes", "frames", "claude (3 calls", "store verdicts", "database save", "total"):
        assert label in report
    assert "database save" in format_timings(store.timings, 0.5, None, 1.0) and "claude" not in format_timings(store.timings, 0.5, None, 1.0)


def test_save_flushes_an_open_session_and_the_data_is_on_disk(store):
    assert store.save().status == 400  # no session
    with store.batch():
        assert store.save().status == 204  # nothing changed yet
        store.set_claude_status("vid", "160", 0, "meme", "x", "miss")
        assert store.save().status == 200
        assert SceneStore(store.path).snapshot().data[0]["claude"]["verdict"] == "meme"  # already readable by others
        store.set_claude_status("vid", "160", 10, "meme", "y", "miss")
    assert SceneStore(store.path).snapshot().data[1]["claude"]["verdict"] == "meme"


def test_negative_save_every_is_refused(store):
    with pytest.raises(ValueError):
        verify(store, [], "edge_histogram", FakeSource(), lambda pairs: [], save_every=-1)
