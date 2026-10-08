import json
import threading
import urllib.error
import urllib.request

import pytest

pytest.importorskip("yaml")
pytest.importorskip("flask")

from werkzeug.serving import make_server

from tests.labeling_support import make_video
from tools.labeling import dataset as ds
from tools.labeling import profiles
from tools.labeling.dataset import Dataset, VideoInfo
from tools.labeling.index import build
from tools.labeling.server import LabelerApp, create_flask_app

FILTERS = {"human_label": "anything_but_meme", "classifier": "flagged",
           "ranges": {"band": {"min": 180}, "margin_luma": {"min": 10.5, "max": 35}}}


def test_a_profile_round_trips_through_its_file(tmp_path):
    path = profiles.save("profile1", FILTERS, tmp_path / "profiles" / "classifier")

    assert path == tmp_path / "profiles" / "classifier" / "profile1.yaml"
    text = path.read_text()
    assert "schema: 1" in text and "name: profile1" in text and "human_label: anything_but_meme" in text
    loaded = profiles.load("profile1", tmp_path / "profiles" / "classifier")
    assert loaded == {"human_label": "anything_but_meme", "classifier": "flagged",
                      "ranges": {"band": {"min": 180.0}, "margin_luma": {"min": 10.5, "max": 35.0}},
                      "invert": []}
    assert "invert" not in text  # only written when something is inverted


def test_defaults_fill_in_and_open_bounds_are_left_out(tmp_path):
    profiles.save("empty", {}, tmp_path)
    profiles.save("open", {"ranges": {"band": {"min": None, "max": 200}, "texture": {}}}, tmp_path)

    assert profiles.load("empty", tmp_path) == {"human_label": "any", "classifier": "any", "ranges": {}, "invert": []}
    assert profiles.load("open", tmp_path)["ranges"] == {"band": {"max": 200.0}}


def test_inverted_filters_are_saved_by_name_sorted_and_deduplicated(tmp_path):
    path = profiles.save("inv", {**FILTERS, "invert": ["classifier", "band", "band"]}, tmp_path)

    assert "invert:\n  - band\n  - classifier" in path.read_text()
    assert profiles.load("inv", tmp_path)["invert"] == ["band", "classifier"]
    with pytest.raises(profiles.ProfileError, match="invert"):
        profiles.save("bad", {"invert": "band"}, tmp_path)
    with pytest.raises(profiles.ProfileError, match="invert"):
        profiles.save("bad", {"invert": [1]}, tmp_path)


def test_saving_again_replaces_and_the_list_is_sorted(tmp_path):
    profiles.save("b", {"classifier": "flagged"}, tmp_path)
    profiles.save("a", {}, tmp_path)
    profiles.save("b", {"classifier": "not_flagged"}, tmp_path)

    assert profiles.list_profiles(tmp_path) == ["a", "b"]
    assert profiles.load("b", tmp_path)["classifier"] == "not_flagged"
    assert profiles.list_profiles(tmp_path / "missing") == []
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("name", ["", "../x", "a/b", "a b", "x" * 65, ".hidden", None, "a.yaml"])
def test_only_plain_names_are_accepted(tmp_path, name):
    with pytest.raises(profiles.ProfileError, match="profile name"):
        profiles.save(name, {}, tmp_path)
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize(
    "filters",
    [{"human_label": "maybe"}, {"classifier": 1}, {"ranges": []}, {"ranges": {"band": {"mid": 1}}},
     {"ranges": {"band": {"min": "x"}}}, {"ranges": {"band": {"min": float("inf")}}}, {"ranges": {"band": 5}}, []],
)
def test_bad_filters_are_rejected(tmp_path, filters):
    with pytest.raises(profiles.ProfileError):
        profiles.save("p", filters, tmp_path)
    assert profiles.list_profiles(tmp_path) == []


def test_loading_a_missing_or_unknown_schema_profile_fails_clearly(tmp_path):
    with pytest.raises(profiles.ProfileNotFound):
        profiles.load("nope", tmp_path)
    (tmp_path / "old.yaml").write_text("schema: 7\nfilters: {}\n")
    with pytest.raises(profiles.ProfileError, match="unsupported schema"):
        profiles.load("old", tmp_path)


def test_the_default_location_is_under_data_datasets():
    assert profiles.PROFILES_DIR.as_posix() == "data/datasets/profiles/classifier"
    assert profiles.DEFAULT_NAME == "profile1"


@pytest.fixture
def web(tmp_path):
    video = make_video(tmp_path / "v.mp4")
    width, height, fps, count = ds.probe(video)
    dataset = Dataset(video=VideoInfo("https://www.youtube.com/watch?v=abcdefghijk", "abcdefghijk", "160",
                                      "avc1", "mp4", width, height, fps, count))
    labeler = LabelerApp(dataset, tmp_path / "datasets" / "abcdefghijk.yaml",
                         build(video, tmp_path / "cache"), video)
    directory = tmp_path / "profiles"
    server = make_server("127.0.0.1", 0, create_flask_app(labeler, profiles_dir=directory), threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", directory
    server.shutdown()
    server.server_close()
    labeler.close()


def call(base, path, method="GET", body=None):
    request = urllib.request.Request(base + path, None if body is None else json.dumps(body).encode(),
                                     {"Content-Type": "application/json"}, method=method)
    return json.load(urllib.request.urlopen(request))


def test_profiles_can_be_saved_listed_and_loaded_over_http(web):
    base, directory = web
    assert call(base, "/api/profiles") == {"profiles": []}

    saved = call(base, "/api/profiles/profile1", "PUT", {"filters": FILTERS})

    assert saved == {"name": "profile1", "profiles": ["profile1"]}
    assert (directory / "profile1.yaml").is_file()
    assert call(base, "/api/profiles/profile1")["filters"]["ranges"]["band"] == {"min": 180.0}
    assert call(base, "/api/profiles") == {"profiles": ["profile1"]}


def test_bad_profile_requests_are_refused_and_write_nothing(web):
    base, directory = web

    for path, body in (("/api/profiles/ok", {"filters": {"human_label": "maybe"}}),
                       ("/api/profiles/ok", {}), ("/api/profiles/a%20b", {"filters": {}})):
        with pytest.raises(urllib.error.HTTPError) as error:
            call(base, path, "PUT", body)
        assert error.value.code == 400
    with pytest.raises(urllib.error.HTTPError) as missing:
        call(base, "/api/profiles/nope")
    assert missing.value.code == 404
    with pytest.raises(urllib.error.HTTPError) as traversal:
        call(base, "/api/profiles/..%2Fsecret", "PUT", {"filters": {}})
    assert traversal.value.code in (400, 404)
    assert not directory.exists() or not list(directory.rglob("*"))
