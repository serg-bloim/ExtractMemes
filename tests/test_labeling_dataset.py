from pathlib import Path

import pytest

pytest.importorskip("yaml")

from tests.labeling_support import FPS, make_video
from tools.labeling import dataset as ds
from tools.labeling.dataset import Dataset, DatasetError, Meme, VideoInfo


@pytest.fixture
def video(tmp_path) -> Path:
    return make_video(tmp_path / "v.mp4")


def info_for(path: Path, **overrides) -> VideoInfo:
    width, height, fps, count = ds.probe(path)
    fields = dict(url="https://www.youtube.com/watch?v=abcdefghijk", id="abcdefghijk", format_id="160",
                  vcodec="avc1", ext="mp4", width=width, height=height, fps=fps, frame_count=count)
    return VideoInfo(**{**fields, **overrides})


def test_save_and_load_round_trip(tmp_path, video):
    dataset = Dataset(video=info_for(video))
    dataset.add(30, 1.2)
    dataset.add(10, 0.4)
    path = tmp_path / "data" / "datasets" / "abcdefghijk.yaml"

    ds.save(dataset, path)
    loaded = ds.load(path)

    assert loaded == dataset
    assert [m.meme_frame for m in loaded.memes] == [10, 30]
    text = path.read_text()
    assert "- {meme_ts: 0.400, meme_frame: 10}" in text
    assert "schema: 1" in text and "mode: standard" in text and "format_id: '160'" in text


def test_add_replaces_the_same_frame_and_remove_drops_it(video):
    dataset = Dataset(video=info_for(video))
    dataset.add(5, 0.2)
    dataset.add(5, 0.2)
    assert dataset.memes == [Meme(0.2, 5)]
    dataset.remove(5)
    assert dataset.memes == []


@pytest.mark.parametrize(
    "edit, message",
    [
        ("schema: 1", "unsupported schema"),
        ("mode: standard", "precise mode is not supported yet"),
    ],
)
def test_load_rejects_unsupported_files(tmp_path, video, edit, message):
    path = tmp_path / "d.yaml"
    ds.save(Dataset(video=info_for(video)), path)
    text = path.read_text()
    path.write_text(text.replace(edit, "schema: 9" if edit.startswith("schema") else "mode: precise"))

    with pytest.raises(DatasetError, match=message):
        ds.load(path)


def test_load_rejects_unsorted_memes(tmp_path, video):
    path = tmp_path / "d.yaml"
    ds.save(Dataset(video=info_for(video)), path)
    path.write_text(path.read_text().replace(
        "memes: []", "memes:\n  - {meme_ts: 1.0, meme_frame: 25}\n  - {meme_ts: 0.4, meme_frame: 10}"))

    with pytest.raises(DatasetError, match="sorted"):
        ds.load(path)


def test_video_id_from_url_and_bare_id():
    assert ds.video_id_from("https://www.youtube.com/watch?v=FtU4MuksCzE&t=5") == "FtU4MuksCzE"
    assert ds.video_id_from("https://youtu.be/FtU4MuksCzE") == "FtU4MuksCzE"
    assert ds.video_id_from("FtU4MuksCzE") == "FtU4MuksCzE"
    with pytest.raises(DatasetError):
        ds.video_id_from("https://example.com/nothing")


@pytest.mark.parametrize("field, value", [("width", 999), ("height", 1), ("fps", 30.0), ("frame_count", 5)])
def test_validate_video_names_the_differing_field(video, field, value):
    with pytest.raises(DatasetError, match=field):
        ds.validate_video(info_for(video, **{field: value}), video)
    ds.validate_video(info_for(video), video)  # the real values pass


def test_ensure_video_reuses_a_downloaded_file_without_the_network(tmp_path, video, monkeypatch):
    dataset = Dataset(video=info_for(video))
    downloads = tmp_path / "downloads"
    target = ds.downloaded_path("abcdefghijk", "160", "mp4", downloads)
    target.parent.mkdir()
    target.write_bytes(video.read_bytes())
    monkeypatch.setattr(ds, "download_format", lambda *a, **k: pytest.fail("must not download"))

    assert ds.ensure_video(dataset, downloads) == target


def test_ensure_video_downloads_the_recorded_format_when_absent(tmp_path, video, monkeypatch):
    dataset = Dataset(video=info_for(video))
    calls = []

    def fake_download(url, selector, downloads_dir, proxy):
        calls.append((url, selector))
        return video, dataset.video

    monkeypatch.setattr(ds, "download_format", fake_download)

    assert ds.ensure_video(dataset, tmp_path / "empty") == video
    assert calls == [(dataset.video.url, "160")]


def test_positive_frames_are_found_by_index_with_their_own_timestamps(video):
    dataset = Dataset(video=info_for(video))
    expected = {i: ts for i, ts, _ in ds.iter_frames(video, lambda i: i in (7, 40))}
    dataset.add(7, expected[7])
    dataset.add(40, expected[40])

    found = list(ds.positive_frames(dataset, video))

    assert [i for i, _, _ in found] == [7, 40]
    assert found[0][1] == pytest.approx(7 / FPS, abs=0.001)
    assert found[0][2].shape == (72, 128, 3)


def test_positive_frames_raise_when_the_timestamp_disagrees(video):
    dataset = Dataset(video=info_for(video))
    dataset.add(7, 3.0)

    with pytest.raises(DatasetError, match="not the labeled video"):
        list(ds.positive_frames(dataset, video))


def test_negative_frames_skip_the_window_around_every_mark(video):
    dataset = Dataset(video=info_for(video))
    dataset.add(37, 37 / FPS)  # 1.48 s

    frames = [(i, ts) for i, ts, _ in ds.negative_frames(dataset, video, fps=5.0, exclusion_window=0.5)]

    assert [i for i, _ in frames][:3] == [0, 5, 10]
    assert all(abs(ts - 37 / FPS) > 0.5 for _, ts in frames)
    assert 37 not in [i for i, _ in frames] and 35 not in [i for i, _ in frames]
    assert 55 in [i for i, _ in frames]
