import json
import threading
import urllib.error
import urllib.request

import numpy as np
import pytest

pytest.importorskip("yaml")

from tests.labeling_support import FPS, make_video
from tools.labeling import dataset as ds
from tools.labeling import index as index_module
from tools.labeling.criteria import CRITERIA, Criterion
from tools.labeling.dataset import Dataset, VideoInfo
from tools.labeling.index import FrameReader, build
from tools.labeling.server import LabelerApp, serve


@pytest.fixture
def video(tmp_path):
    return make_video(tmp_path / "v.mp4", frames=75)


@pytest.fixture
def labeler(tmp_path, video):
    width, height, fps, count = ds.probe(video)
    dataset = Dataset(video=VideoInfo("https://www.youtube.com/watch?v=abcdefghijk", "abcdefghijk", "160",
                                      "avc1", "mp4", width, height, fps, count))
    dataset_file = tmp_path / "datasets" / "abcdefghijk.yaml"
    index = build(video, tmp_path / "cache", fps=5.0)
    app = LabelerApp(dataset, dataset_file, index, video)
    server = serve(app, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield app, base, dataset_file
    server.shutdown()
    server.server_close()
    app.close()


def get(url, headers=None):
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}))


def post(base, path, body):
    request = urllib.request.Request(base + path, json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(request))


def test_index_has_a_row_per_scanned_frame_with_scores_and_verdict(tmp_path, video):
    index = build(video, tmp_path / "cache", fps=5.0)

    assert index.step == 5
    assert index.rows.tolist() == list(range(0, 75, 5))
    assert len(index.pts) == 75 and index.pts[5] == pytest.approx(5 / FPS, abs=0.001)
    assert set(index.scores) == {c.name for c in CRITERIA}
    assert all(len(v) == 15 for v in index.scores.values()) and len(index.verdict) == 15
    assert len(list(index.thumb_dir.glob("*.jpg"))) == 15


def test_a_second_build_reads_the_cache_and_a_new_criterion_scores_only_itself(tmp_path, video, monkeypatch):
    build(video, tmp_path / "cache", fps=5.0)
    monkeypatch.setattr(index_module, "_run_pass", lambda *a, **k: pytest.fail("cache was not used"))
    build(video, tmp_path / "cache", fps=5.0)
    monkeypatch.undo()

    def brightness(frame):
        return float(frame.mean())

    passes = []
    original = index_module._run_pass
    monkeypatch.setattr(index_module, "_run_pass",
                        lambda *a: passes.append(sorted(c.name for c in a[3] if c.name in a[4])) or original(*a))

    index = build(video, tmp_path / "cache", fps=5.0, criteria=[*CRITERIA, Criterion("brightness", brightness)])

    assert passes == [["brightness"]]
    assert len(index.scores["brightness"]) == 15


def test_frame_reader_returns_the_right_frame_for_any_access_order(tmp_path, video):
    index = build(video, tmp_path / "cache", fps=5.0)
    truth = {i: f for i, _, f in ds.iter_frames(video)}
    reader = FrameReader(video, index.pts)
    try:
        for i in (0, 1, 2, 60, 59, 20, 74, 3, 3, 40, 10):
            assert np.array_equal(reader.get(i), truth[i]), f"frame {i}"
        with pytest.raises(IndexError):
            reader.get(75)
    finally:
        reader.close()


def test_state_endpoint_describes_the_video_and_scores(labeler):
    app, base, _ = labeler

    state = json.load(get(base + "/api/state"))

    assert state["frame_count"] == 75 and state["step"] == 5 and state["memes"] == []
    assert state["rows"] == list(range(0, 75, 5))
    assert [c["name"] for c in state["criteria"]] == [c.name for c in CRITERIA]
    assert len(state["verdict"]) == 15 and len(state["scores"]["band"]) == 15


def test_thumbnail_and_frame_endpoints_serve_jpegs(labeler):
    _, base, _ = labeler

    assert get(base + "/thumb/10.jpg").read(2) == b"\xff\xd8"
    full = get(base + "/frame/11.jpg")  # a frame the scan doesn't sample
    assert full.headers["Content-Type"] == "image/jpeg" and full.read(2) == b"\xff\xd8"
    with pytest.raises(urllib.error.HTTPError) as missing:
        get(base + "/thumb/11.jpg")
    assert missing.value.code == 404
    with pytest.raises(urllib.error.HTTPError) as past_end:
        get(base + "/frame/999.jpg")
    assert past_end.value.code == 404


def test_marking_writes_the_dataset_on_every_change(labeler):
    app, base, dataset_file = labeler
    assert not dataset_file.exists()  # created on the first mark

    memes = post(base, "/api/mark", {"frame": 40, "on": True})["memes"]
    assert memes == [{"ts": pytest.approx(40 / FPS, abs=0.001), "frame": 40}]
    post(base, "/api/mark", {"frame": 12, "on": True})
    loaded = ds.load(dataset_file)
    assert [m.meme_frame for m in loaded.memes] == [12, 40]

    post(base, "/api/move", {"from": 12, "to": 14})
    assert [m.meme_frame for m in ds.load(dataset_file).memes] == [14, 40]

    post(base, "/api/mark", {"frame": 40, "on": False})
    assert [m.meme_frame for m in ds.load(dataset_file).memes] == [14]
    assert ds.load(dataset_file).memes[0].meme_ts == pytest.approx(14 / FPS, abs=0.001)


def test_marking_many_frames_is_one_save_and_unmarking_many_removes_them(labeler):
    app, base, dataset_file = labeler

    memes = post(base, "/api/mark_many", {"frames": [30, 5, 10], "on": True})["memes"]
    assert [m["frame"] for m in memes] == [5, 10, 30]
    assert [m.meme_frame for m in ds.load(dataset_file).memes] == [5, 10, 30]

    memes = post(base, "/api/mark_many", {"frames": [5, 30], "on": False})["memes"]
    assert [m["frame"] for m in memes] == [10]
    assert [m.meme_frame for m in ds.load(dataset_file).memes] == [10]


def test_a_bad_frame_in_a_batch_marks_nothing(labeler):
    _, base, dataset_file = labeler

    for body in ({"frames": [5, 999], "on": True}, {"frames": [], "on": True}, {"frames": "5", "on": True}):
        with pytest.raises(urllib.error.HTTPError) as error:
            post(base, "/api/mark_many", body)
        assert error.value.code == 400
    assert not dataset_file.exists()


def test_bad_mark_requests_are_rejected(labeler):
    _, base, dataset_file = labeler

    for body in ({"frame": 999, "on": True}, {"frame": -1, "on": True}, {"frame": "3", "on": True}, {}):
        with pytest.raises(urllib.error.HTTPError) as error:
            post(base, "/api/mark", body)
        assert error.value.code == 400
    assert not dataset_file.exists()


def test_only_the_page_and_its_api_are_served_to_this_host(labeler):
    _, base, _ = labeler

    assert b"Frame Labeler" in get(base + "/").read()
    for path in ("/etc/passwd", "/../dataset.py", "/api/other", "/frame/x.jpg"):
        with pytest.raises(urllib.error.HTTPError) as error:
            get(base + path)
        assert error.value.code == 404
    with pytest.raises(urllib.error.HTTPError) as foreign:
        get(base + "/api/state", {"Host": "evil.example"})
    assert foreign.value.code == 403
    with pytest.raises(urllib.error.HTTPError) as cross_site:
        post_request = urllib.request.Request(base + "/api/mark", b'{"frame":1,"on":true}',
                                              {"Origin": "http://evil.example"})
        urllib.request.urlopen(post_request)
    assert cross_site.value.code == 403
