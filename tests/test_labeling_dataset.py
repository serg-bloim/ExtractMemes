from pathlib import Path

import pytest

pytest.importorskip("yaml")

from tests.labeling_support import FPS, make_video
from tools.labeling import dataset as ds
from tools.labeling.dataset import Dataset, DatasetError, Meme, NotMeme, VideoInfo


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

    def fake_download(url, selector, downloads_dir, proxy, progress=None):
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


def test_not_memes_round_trip_and_exclude_the_meme_label(tmp_path, video):
    dataset = Dataset(video=info_for(video))
    dataset.add(10, 0.4)
    dataset.add_not_meme(30, 1.2)
    dataset.add_not_meme(10, 0.4)  # replaces the meme label of frame 10
    path = tmp_path / "d.yaml"

    ds.save(dataset, path)
    loaded = ds.load(path)

    assert loaded.memes == [] and loaded.not_memes == [NotMeme(0.4, 10), NotMeme(1.2, 30)]
    assert "- {not_meme_ts: 1.200, not_meme_frame: 30}" in path.read_text()
    loaded.add(30, 1.2)  # and back again
    assert loaded.memes == [Meme(1.2, 30)] and loaded.not_memes == [NotMeme(0.4, 10)]


def test_a_file_without_not_memes_is_valid_and_a_clash_is_rejected(tmp_path, video):
    path = tmp_path / "d.yaml"
    ds.save(Dataset(video=info_for(video)), path)
    assert "not_memes" not in path.read_text() and ds.load(path).not_memes == []

    path.write_text(path.read_text().replace("memes: []", "memes:\n  - {meme_ts: 0.4, meme_frame: 10}\n"
                                             "not_memes:\n  - {not_meme_ts: 0.4, not_meme_frame: 10}"))
    with pytest.raises(DatasetError, match="both a meme and a not-meme"):
        ds.load(path)


def test_not_meme_frames_are_found_by_index_even_next_to_a_mark(video):
    dataset = Dataset(video=info_for(video))
    ts = {i: t for i, t, _ in ds.iter_frames(video, lambda i: i in (20, 22))}
    dataset.add(20, ts[20])
    dataset.add_not_meme(22, ts[22])

    assert [i for i, _, _ in ds.not_meme_frames(dataset, video)] == [22]
    dataset.not_memes = [NotMeme(9.0, 22)]
    with pytest.raises(DatasetError, match="not the labeled video"):
        list(ds.not_meme_frames(dataset, video))


def fmt(format_id, height, fps, av1=False, width=None):
    return {"format_id": format_id, "height": height, "width": width or height * 16 // 9, "fps": fps, "av1": av1}


def test_preferred_format_wants_25_fps_then_the_smallest_resolution_then_not_av1():
    # 25+ fps beats everything else, even a larger picture
    assert ds.preferred_format([fmt("a", 144, 13), fmt("b", 360, 25)]) == "b"
    # among 25+ fps, the smallest resolution
    assert ds.preferred_format([fmt("a", 360, 30), fmt("b", 144, 25), fmt("c", 144, 60)]) in ("b", "c")
    # same fps class and resolution: not AV1 wins, whatever the order
    assert ds.preferred_format([fmt("av", 144, 25, av1=True), fmt("h264", 144, 25)]) == "h264"
    assert ds.preferred_format([fmt("h264", 144, 25), fmt("av", 144, 25, av1=True)]) == "h264"
    # a smaller AV1 picture still beats a bigger non-AV1 one: resolution outranks codec
    assert ds.preferred_format([fmt("big", 360, 25), fmt("av", 144, 25, av1=True)]) == "av"
    # nothing reaches 25 fps (or the fps is unknown): fall back to resolution, then codec
    assert ds.preferred_format([fmt("a", 360, 13), fmt("b", 144, None), fmt("c", 144, 13, av1=True)]) == "b"
    assert ds.preferred_format([]) is None


def test_a_meme_with_a_start_and_end_round_trips_and_covers_its_frames(tmp_path, video):
    dataset = Dataset(video=info_for(video))
    dataset.add(30, 1.2)
    dataset.set_edge(27, "start", lambda f: f / FPS, 1.0)
    dataset.set_edge(34, "end", lambda f: f / FPS, 1.0)
    path = tmp_path / "d.yaml"

    ds.save(dataset, path)
    loaded = ds.load(path)

    assert loaded == dataset
    assert loaded.memes == [Meme(1.2, 30, 1.08, 27, 1.36, 34)]
    assert all(loaded.meme_at(f) for f in range(27, 35)) and not loaded.meme_at(35)
    assert "{meme_ts: 1.200, meme_frame: 30, meme_start_ts: 1.080, meme_start_frame: 27, meme_end_ts: 1.360, meme_end_frame: 34}" in path.read_text()


def test_setting_an_edge_past_the_anchor_moves_the_anchor_into_the_range():
    dataset = Dataset(video=None)
    ts = lambda f: f / 10
    dataset.add(30, 3.0)
    dataset.set_edge(36, "start", ts, 1.0)       # nearest meme is the one at 30; its start moves past it
    assert dataset.memes == [Meme(3.6, 36, 3.6, 36)]
    dataset.set_edge(40, "end", ts, 1.0)
    assert (dataset.memes[0].first, dataset.memes[0].last) == (36, 40)
    dataset.set_edge(80, "end", ts, 1.0)          # too far from the meme: a new one, ending (and starting) at 80
    assert [(m.first, m.last) for m in dataset.memes] == [(36, 40), (80, 80)]


def test_a_range_can_neither_invert_nor_overlap_and_a_not_meme_cannot_sit_in_it():
    ts = lambda f: f / 10
    dataset = Dataset(video=None)
    dataset.set_edge(20, "start", ts, 1.0)
    dataset.set_edge(25, "end", ts, 1.0)
    with pytest.raises(ValueError):
        dataset.set_edge(15, "end", ts, 1.0)
    with pytest.raises(ValueError):
        dataset.set_edge(22, "bogus", ts, 1.0)
    with pytest.raises(ValueError):
        dataset.add_not_meme(22, 2.2)
    dataset.memes.append(Meme(2.4, 24, 2.3, 23, 2.6, 26))   # a hand-made overlap: set_edge refuses to leave it overlapping
    with pytest.raises(ValueError, match="overlap"):
        dataset.set_edge(24, "end", ts, 1.0)


def test_load_rejects_a_range_the_anchor_is_outside_of_or_that_overlaps(tmp_path, video):
    good = Dataset(video=info_for(video), memes=[Meme(1.0, 25, 0.8, 20, 1.2, 30), Meme(2.0, 50)])
    path = tmp_path / "d.yaml"
    ds.save(good, path)
    assert ds.load(path) == good
    for bad in (Meme(1.0, 25, 1.1, 28, 1.2, 30), Meme(1.0, 25, 0.8, 20, 2.2, 55)):
        ds.save(Dataset(video=info_for(video), memes=[bad, Meme(2.0, 50)]), path)
        with pytest.raises(DatasetError, match="start and end"):
            ds.load(path)


def test_negative_frames_skip_a_memes_whole_range_plus_the_window(video):
    dataset = Dataset(video=info_for(video), memes=[Meme(1.2, 30, 0.8, 20, 1.6, 40)])  # 0.8 s .. 1.6 s

    kept = [i for i, _, _ in ds.negative_frames(dataset, video, fps=5.0, exclusion_window=0.5)]

    assert not any(0.3 - 1e-9 <= i / FPS <= 2.1 + 1e-9 for i in kept)
    assert 0 in kept and 55 in kept


def test_set_range_replaces_the_memes_it_overlaps_and_drops_not_memes_inside():
    ts = lambda f: f / 10
    dataset = Dataset(video=None, memes=[Meme(1.0, 10), Meme(3.0, 30, 2.8, 28, 3.4, 34), Meme(9.0, 90)],
                      not_memes=[NotMeme(2.0, 20), NotMeme(6.0, 60)])

    dataset.set_range(25, 40, ts)

    assert dataset.memes == [Meme(1.0, 10), Meme(3.2, 32, 2.5, 25, 4.0, 40), Meme(9.0, 90)]   # frame = the center
    assert dataset.not_memes == [NotMeme(2.0, 20), NotMeme(6.0, 60)]   # none inside 25..40
    dataset.set_range(55, 65, ts)
    assert dataset.memes[2] == Meme(6.0, 60, 5.5, 55, 6.5, 65) and dataset.not_memes == [NotMeme(2.0, 20)]
    with pytest.raises(ValueError):
        dataset.set_range(9, 3, ts)


def test_add_many_makes_each_run_a_region_and_each_lone_frame_a_single_meme():
    ts = lambda f: f / 10
    dataset = Dataset(video=None, memes=[Meme(1.4, 14), Meme(9.0, 90, 8.0, 80, 9.5, 95)], not_memes=[NotMeme(1.2, 12)])

    dataset.add_many([30, 10, 11, 12, 13, 14, 15, 50, 51], ts)

    assert dataset.memes == [Meme(1.2, 12, 1.0, 10, 1.5, 15),   # the single mark at 14 is unmarked
                             Meme(3.0, 30), Meme(5.0, 50, 5.0, 50, 5.1, 51), Meme(9.0, 90, 8.0, 80, 9.5, 95)]
    assert dataset.not_memes == []
    dataset.add_many([81, 82], ts)                              # inside an existing region: it is replaced by the new run
    assert Meme(8.1, 81, 8.1, 81, 8.2, 82) in dataset.memes


def test_a_start_and_end_center_the_meme_and_unmark_individual_marks_inside():
    ts = lambda f: f / 10
    dataset = Dataset(video=None, memes=[Meme(1.4, 14), Meme(5.0, 50)])

    dataset.set_edge(12, "start", ts, 1.0)
    assert dataset.memes[0] == Meme(1.4, 14, 1.2, 12, None, None)   # only a start: its frame stays
    dataset.set_edge(18, "end", ts, 1.0)
    assert dataset.memes[0] == Meme(1.5, 15, 1.2, 12, 1.8, 18)       # both edges: the frame is the center
    dataset.set_edge(24, "end", ts, 1.0)
    assert dataset.memes[0] == Meme(1.8, 18, 1.2, 12, 2.4, 24)       # a new end moves the center

    dataset.memes = [Meme(1.4, 14, 1.2, 12, 2.2, 22), Meme(1.8, 18)]  # an individual mark inside the window
    dataset.set_edge(24, "end", ts, 1.0)
    assert dataset.memes == [Meme(1.8, 18, 1.2, 12, 2.4, 24)]        # is unmarked
