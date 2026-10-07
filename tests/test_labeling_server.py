import json
import threading
from pathlib import Path
import urllib.error
import urllib.request

import cv2
import numpy as np
import pytest

pytest.importorskip("yaml")
pytest.importorskip("flask")

from tests.labeling_support import FPS, make_video
from tools.labeling import dataset as ds
from tools.labeling import index as index_module
from extract_memes.criteria import Criterion, all_criteria
from extract_memes.heuristic_classifier import HeuristicClassifier
from tools.labeling.dataset import Dataset, VideoInfo
from tools.labeling.index import FrameReader, build
from werkzeug.serving import make_server

from tools.labeling.server import LabelerApp, create_flask_app


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
    server = make_server("127.0.0.1", 0, create_flask_app(app), threaded=True)
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
    assert set(index.scores) == set(all_criteria())
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

    index = build(video, tmp_path / "cache", fps=5.0, criteria=[*all_criteria().values(), Criterion("brightness", brightness)])

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
    assert [c["name"] for c in state["criteria"]] == list(all_criteria())
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


def test_small_frames_are_served_for_every_native_frame(labeler):
    app, base, _ = labeler
    image = cv2.imdecode(np.frombuffer(get(base + "/small/13.jpg").read(), np.uint8), cv2.IMREAD_COLOR)
    assert image.shape[1] == 160 and image.shape[0] < image.shape[1]
    with pytest.raises(urllib.error.HTTPError) as past_end:
        get(base + "/small/999.jpg")
    assert past_end.value.code == 404


def test_marking_writes_the_dataset_on_every_change(labeler):
    app, base, dataset_file = labeler
    assert not dataset_file.exists()  # created on the first mark

    memes = post(base, "/api/mark", {"frame": 40, "on": True})["memes"]
    assert memes == [{"ts": pytest.approx(40 / FPS, abs=0.001), "frame": 40, "start_ts": None, "start_frame": None,
                      "end_ts": None, "end_frame": None}]
    post(base, "/api/mark", {"frame": 12, "on": True})
    loaded = ds.load(dataset_file)
    assert [m.meme_frame for m in loaded.memes] == [12, 40]

    post(base, "/api/move", {"from": 12, "to": 14})
    assert [m.meme_frame for m in ds.load(dataset_file).memes] == [14, 40]

    post(base, "/api/mark", {"frame": 40, "on": False})
    assert [m.meme_frame for m in ds.load(dataset_file).memes] == [14]
    assert ds.load(dataset_file).memes[0].meme_ts == pytest.approx(14 / FPS, abs=0.001)


def test_start_and_end_of_a_meme_are_saved_and_the_range_is_one_meme(labeler):
    app, base, dataset_file = labeler
    post(base, "/api/mark", {"frame": 30, "on": True})

    post(base, "/api/edge", {"frame": 27, "edge": "start", "window": 1})   # within 1 s of the mark: same meme
    memes = post(base, "/api/edge", {"frame": 34, "edge": "end", "window": 1})["memes"]

    assert [(m["start_frame"], m["frame"], m["end_frame"]) for m in memes] == [(27, 30, 34)]
    saved = ds.load(dataset_file).memes
    assert (saved[0].start_frame, saved[0].end_frame) == (27, 34)
    assert saved[0].end_ts == pytest.approx(34 / FPS, abs=0.001)
    assert "meme_start_frame: 27" in dataset_file.read_text()

    post(base, "/api/edge", {"frame": 60, "edge": "start", "window": 1})   # far away: a new meme
    assert [m.first for m in ds.load(dataset_file).memes] == [27, 60]

    post(base, "/api/mark", {"frame": 31, "on": False})                    # unmarking inside the range removes it
    assert [m.first for m in ds.load(dataset_file).memes] == [60]


def test_marking_many_frames_makes_runs_into_regions_and_lone_frames_single_memes(labeler):
    app, base, dataset_file = labeler
    post(base, "/api/mark", {"frame": 14, "on": True})

    memes = post(base, "/api/mark_many", {"frames": [30, 10, 11, 12, 13, 14, 15, 20], "on": True})["memes"]

    assert [(m["start_frame"], m["frame"], m["end_frame"]) for m in memes] == [
        (10, 14, 15), (None, 20, None), (None, 30, None)]
    saved = ds.load(dataset_file).memes
    assert (saved[0].start_frame, saved[0].end_frame) == (10, 15)
    assert saved[0].end_ts == pytest.approx(15 / FPS, abs=0.001)

    post(base, "/api/mark_many", {"frames": [12, 13], "on": False})   # unmarking a frame inside removes its meme
    assert [m.meme_frame for m in ds.load(dataset_file).memes] == [20, 30]


def test_bad_edges_are_rejected_and_change_nothing(labeler):
    app, base, dataset_file = labeler
    post(base, "/api/edge", {"frame": 20, "edge": "start"})
    post(base, "/api/edge", {"frame": 24, "edge": "end"})
    saved = dataset_file.read_text()

    for body in ({"frame": 30, "edge": "end", "window": 100},   # window out of range
                 {"frame": 20, "edge": "middle"},
                 {"frame": 999, "edge": "end"},
                 {"frame": 18, "edge": "end"},                  # the meme at 20..24 can't end before it starts
                 {"frame": 26, "edge": "start"}):               # ...nor start after it ends
        with pytest.raises(urllib.error.HTTPError) as bad:
            post(base, "/api/edge", body)
        assert bad.value.code == 400, body
    assert dataset_file.read_text() == saved


def test_a_not_meme_inside_a_range_is_refused_and_the_batch_is_all_or_nothing(labeler):
    app, base, dataset_file = labeler
    post(base, "/api/edge", {"frame": 20, "edge": "start"})
    post(base, "/api/edge", {"frame": 24, "edge": "end"})
    saved = dataset_file.read_text()

    with pytest.raises(urllib.error.HTTPError) as bad:
        post(base, "/api/mark_many", {"frames": [50, 22], "on": True, "label": "not_meme"})
    assert bad.value.code == 400
    assert dataset_file.read_text() == saved and app.dataset.not_memes == []
    with pytest.raises(urllib.error.HTTPError):
        post(base, "/api/move", {"from": 22, "to": 40})      # a range is edited, not moved


def test_marking_many_frames_is_one_save_and_unmarking_many_removes_them(labeler):
    app, base, dataset_file = labeler

    memes = post(base, "/api/mark_many", {"frames": [30, 5, 10], "on": True})["memes"]
    assert [m["frame"] for m in memes] == [5, 10, 30]
    assert [m.meme_frame for m in ds.load(dataset_file).memes] == [5, 10, 30]

    memes = post(base, "/api/mark_many", {"frames": [5, 30], "on": False})["memes"]
    assert [m["frame"] for m in memes] == [10]
    assert [m.meme_frame for m in ds.load(dataset_file).memes] == [10]


def test_not_meme_labels_are_saved_and_replace_the_meme_label(labeler):
    _, base, dataset_file = labeler

    post(base, "/api/mark", {"frame": 12, "on": True})
    labels = post(base, "/api/mark", {"frame": 12, "on": True, "label": "not_meme"})
    assert labels["memes"] == [] and [n["frame"] for n in labels["not_memes"]] == [12]
    labels = post(base, "/api/mark_many", {"frames": [20, 30], "on": True, "label": "not_meme"})
    assert [n["frame"] for n in labels["not_memes"]] == [12, 20, 30]
    saved = ds.load(dataset_file)
    assert saved.memes == [] and [n.not_meme_frame for n in saved.not_memes] == [12, 20, 30]
    assert json.load(get(base + "/api/state"))["not_memes"][0]["frame"] == 12

    labels = post(base, "/api/mark", {"frame": 12, "on": False, "label": "not_meme"})
    assert [n["frame"] for n in labels["not_memes"]] == [20, 30]
    with pytest.raises(urllib.error.HTTPError) as error:
        post(base, "/api/mark", {"frame": 12, "on": True, "label": "maybe"})
    assert error.value.code == 400


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


# --- opening a video from the page ----------------------------------------------------------------


from tools.labeling.workspace import Workspace  # noqa: E402


def make_labeler(tmp_path, video, video_id="abcdefghijk"):
    width, height, fps, count = ds.probe(video)
    dataset = Dataset(video=VideoInfo(f"https://www.youtube.com/watch?v={video_id}", video_id, "160",
                                      "avc1", "mp4", width, height, fps, count))
    index = build(video, tmp_path / f"cache_{video_id}", fps=5.0)
    return LabelerApp(dataset, tmp_path / "datasets" / f"{video_id}.yaml", index, video)


@pytest.fixture
def empty_workspace(tmp_path, video):
    """A workspace with nothing open; its opener hands out a labeler for the requested id."""
    calls, gate = [], threading.Event()
    gate.set()

    def opener(source, format_id, progress):
        calls.append((source, format_id))
        progress("Downloading video", 0.5)
        gate.wait(5)
        if source.endswith("FAILFAILFAI"):
            raise RuntimeError("no such video")
        return make_labeler(tmp_path, video, video_id=source[-11:])

    def inspector(url):
        if url.endswith("FAILFAILFAI"):
            raise ds.DatasetError("video unavailable")
        return {"id": url[-11:], "title": "A title", "thumbnail": "https://i.ytimg.com/x.jpg",
                "formats": [{"format_id": "160", "height": 144, "width": 256, "fps": 13},
                              {"format_id": "401", "height": 1080, "width": 1920, "fps": 25}]}

    workspace = Workspace(opener, datasets_dir=tmp_path / "datasets", inspector=inspector)
    server = make_server("127.0.0.1", 0, create_flask_app(workspace), threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield workspace, f"http://127.0.0.1:{server.server_address[1]}", calls, gate
    server.shutdown()
    server.server_close()


def status_of(base):
    return json.load(get(base + "/api/status"))


def test_with_no_video_open_the_page_and_status_work_but_the_video_api_says_so(empty_workspace):
    _, base, _, _ = empty_workspace

    assert b"Open a video" in get(base + "/").read()
    status = status_of(base)
    assert status["state"] == "idle" and status["video"] is None and status["datasets"] == []
    with pytest.raises(urllib.error.HTTPError) as no_state:
        get(base + "/api/state")
    assert no_state.value.code == 409
    with pytest.raises(urllib.error.HTTPError) as no_frame:
        get(base + "/frame/3.jpg")
    assert no_frame.value.code == 404
    with pytest.raises(urllib.error.HTTPError) as no_mark:
        post(base, "/api/mark", {"frame": 1, "on": True})
    assert no_mark.value.code == 409


def test_opening_a_video_loads_it_in_the_background_then_serves_it(empty_workspace):
    workspace, base, calls, _ = empty_workspace

    reply = post(base, "/api/open", {"source": "https://youtu.be/AAAAAAAAAAA?t=5"})
    assert reply["state"] == "loading"
    workspace.wait(10)

    status = status_of(base)
    assert status["state"] == "ready" and status["video"] == "AAAAAAAAAAA"
    assert calls == [("https://www.youtube.com/watch?v=AAAAAAAAAAA", None)]  # built from the id
    assert json.load(get(base + "/api/state"))["video"]["id"] == "AAAAAAAAAAA"


def test_loading_shows_progress_and_a_second_open_is_refused_until_it_finishes(empty_workspace):
    workspace, base, _, gate = empty_workspace
    gate.clear()

    post(base, "/api/open", {"source": "BBBBBBBBBBB"})
    for _ in range(100):
        if status_of(base)["progress"] == 0.5:
            break
        threading.Event().wait(0.02)
    status = status_of(base)
    assert status["state"] == "loading" and status["message"] == "Downloading video"
    assert status["progress"] == 0.5
    with pytest.raises(urllib.error.HTTPError) as busy:
        post(base, "/api/open", {"source": "CCCCCCCCCCC"})
    assert busy.value.code == 409

    gate.set()
    workspace.wait(10)
    assert status_of(base)["video"] == "BBBBBBBBBBB"


def test_a_failed_open_is_reported_and_the_open_video_stays_open(empty_workspace):
    workspace, base, _, _ = empty_workspace
    post(base, "/api/open", {"source": "AAAAAAAAAAA"})
    workspace.wait(10)

    post(base, "/api/open", {"source": "FAILFAILFAI"})
    workspace.wait(10)

    status = status_of(base)
    assert status["state"] == "error" and "no such video" in status["message"]
    assert status["video"] == "AAAAAAAAAAA"
    assert json.load(get(base + "/api/state"))["video"]["id"] == "AAAAAAAAAAA"
    post(base, "/api/open", {"source": "DDDDDDDDDDD"})  # and another can be opened afterwards
    workspace.wait(10)
    assert status_of(base)["video"] == "DDDDDDDDDDD"


@pytest.mark.parametrize("source", ["https://example.com/clip", "", None, 12, "short"])
def test_only_youtube_ids_are_accepted(empty_workspace, source):
    _, base, calls, _ = empty_workspace

    with pytest.raises(urllib.error.HTTPError) as error:
        post(base, "/api/open", {"source": source})

    assert error.value.code == 400 and calls == []


def test_existing_datasets_are_listed_for_the_page(empty_workspace, tmp_path, video):
    _, base, _, _ = empty_workspace
    labeler = make_labeler(tmp_path, video, video_id="EEEEEEEEEEE")
    labeler.mark(10, True)
    labeler.mark(20, True, "not_meme")

    assert status_of(base)["datasets"] == [{"id": "EEEEEEEEEEE", "memes": 1, "not_memes": 1}]


def test_inspect_returns_the_video_details_and_formats(empty_workspace):
    _, base, calls, _ = empty_workspace

    info = post(base, "/api/inspect", {"source": "https://youtu.be/AAAAAAAAAAA"})

    assert info["id"] == "AAAAAAAAAAA" and info["title"] == "A title"
    assert [f["format_id"] for f in info["formats"]] == ["160", "401"]
    assert info["dataset"] is None
    assert info["preselected"] == "401"  # the only 25+ fps format in the fake lookup
    assert calls == []  # looking up doesn't load anything


def test_inspect_reports_the_dataset_a_video_already_has(empty_workspace, tmp_path, video):
    _, base, _, _ = empty_workspace
    labeler = make_labeler(tmp_path, video, video_id="EEEEEEEEEEE")
    labeler.mark(10, True)

    info = post(base, "/api/inspect", {"source": "EEEEEEEEEEE"})

    assert info["dataset"] == {"format_id": "160", "memes": 1, "not_memes": 0}


@pytest.mark.parametrize("source", ["https://example.com/x", None, "FAILFAILFAI"])
def test_inspect_rejects_bad_sources_and_failed_lookups(empty_workspace, source):
    _, base, _, _ = empty_workspace

    with pytest.raises(urllib.error.HTTPError) as error:
        post(base, "/api/inspect", {"source": source})

    assert error.value.code == 400


def test_open_passes_the_chosen_format_and_refuses_format_expressions(empty_workspace):
    workspace, base, calls, _ = empty_workspace

    post(base, "/api/open", {"source": "AAAAAAAAAAA", "format_id": "401"})
    workspace.wait(10)
    assert calls == [("https://www.youtube.com/watch?v=AAAAAAAAAAA", "401")]

    for bad in ("160+140", "bestvideo[height<=144]", "worst/best", 160):
        with pytest.raises(urllib.error.HTTPError) as error:
            post(base, "/api/open", {"source": "AAAAAAAAAAA", "format_id": bad})
        assert error.value.code == 400
    assert len(calls) == 1


def test_the_labelers_scores_and_verdicts_are_what_the_pipeline_scan_computes(tmp_path, video):
    from extract_memes.frame_extractor import sample_frames

    index = build(video, tmp_path / "cache", fps=5.0)
    classifier = HeuristicClassifier()

    scanned = list(sample_frames(video, fps=5.0))

    assert [i for i, _, _ in scanned] == index.rows.tolist()
    for row, (_, timestamp, frame) in enumerate(scanned):
        for name, criterion in all_criteria().items():
            assert index.scores[name][row] == pytest.approx(criterion.score(frame), rel=1e-5, abs=1e-5), name
        assert bool(index.verdict[row]) == classifier.is_meme_frame(frame)
        assert timestamp == pytest.approx(index.pts[index.rows[row]], abs=0.001)


def test_the_page_gets_the_classifiers_thresholds_for_the_criteria_it_uses(labeler):
    _, base, _ = labeler

    criteria = {c["name"]: c for c in json.load(get(base + "/api/state"))["criteria"]}

    assert criteria["band"]["thresholds"] == [{"op": ">", "value": 180.0}]
    assert criteria["texture"]["thresholds"] == []
    assert criteria["margin_luma"]["description"]


def test_frame_reader_decodes_from_the_start_when_a_seek_cannot_reach_an_early_frame(tmp_path, video, monkeypatch):
    """Some H.264 streams land a seek past the first ~100 frames, even a seek to frame 0."""
    index = build(video, tmp_path / "cache", fps=5.0)
    truth = {i: f for i, _, f in ds.iter_frames(video)}
    reader = FrameReader(video, index.pts)

    def seek_that_lands_late(start):
        reader._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        for _ in range(6):
            ok, frame = reader._cap.read()
        reader._remember(5, frame)
        reader._pos = 6
        return 5

    monkeypatch.setattr(reader, "_seek", seek_that_lands_late)
    try:
        for i in (2, 0, 4, 40, 3):
            assert np.array_equal(reader.get(i), truth[i]), f"frame {i}"
    finally:
        reader.close()


def test_image_urls_are_versioned_per_video_so_the_browser_cannot_mix_videos_up(tmp_path):
    """/thumb/4256.jpg is cached for an hour; in another video the same URL is another picture."""
    first = make_video(tmp_path / "a.mp4", frames=75)
    second = make_video(tmp_path / "b.mp4", frames=60)
    one = make_labeler(tmp_path, first, video_id="AAAAAAAAAAA")
    two = make_labeler(tmp_path, second, video_id="BBBBBBBBBBB")
    again = make_labeler(tmp_path, first, video_id="AAAAAAAAAAA")

    assert one.state()["version"] != two.state()["version"]
    assert one.state()["version"] == again.state()["version"]  # stable for the same file
    assert one.state()["version"].startswith("AAAAAAAAAAA-160-")
    html = (Path(__file__).parent.parent / "tools" / "labeling" / "page.html").read_text()
    assert html.count("?v=") >= 3 and "S.version" in html  # thumbs, the large frame and its preloads
