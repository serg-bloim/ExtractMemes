from unittest import mock

import cv2
import numpy as np
import pytest

from extract_memes.frame_extractor import frame_at, sample_frames


def test_sample_frames_at_one_fps(short_video):
    frames = list(sample_frames(short_video, fps=1.0))

    assert len(frames) == 79
    assert 70 <= len(frames) <= 85


def test_sample_frames_at_default_fps(short_video):
    frames = list(sample_frames(short_video))

    assert len(frames) == 164
    assert [index for index, _, _ in frames] == [12 * n for n in range(164)]
    timestamps = [timestamp for _, timestamp, _ in frames]
    assert all(earlier < later for earlier, later in zip(timestamps, timestamps[1:]))
    assert timestamps[22] == pytest.approx(10.56)
    assert all(frame.shape[:2] == (144, 256) for _, _, frame in frames)


def test_frame_at_shape(short_video):
    assert frame_at(short_video, 10.0).shape[:2] == (144, 256)


def test_frame_at_matches_sequential_decode(short_video):
    indices = [0, 12, 150, 288]
    decoded = {}
    capture = cv2.VideoCapture(str(short_video))
    try:
        for index in range(max(indices) + 1):
            ok, frame = capture.read()
            assert ok
            if index in indices:
                decoded[index] = frame
    finally:
        capture.release()

    for index in indices:
        assert np.array_equal(frame_at(short_video, index / 25), decoded[index]), index


def test_frame_at_past_the_end_raises(short_video):
    with pytest.raises(RuntimeError, match=r"3600.*short\.mp4"):
        frame_at(short_video, 3600.0)


def test_missing_file_raises_on_iteration(tmp_path):
    missing = tmp_path / "missing.mp4"
    frames = sample_frames(missing)  # a generator: nothing is opened yet

    with pytest.raises(RuntimeError, match="Could not open video file: .*missing.mp4"):
        next(frames)


def test_frame_at_missing_file_raises(tmp_path):
    missing = tmp_path / "missing.mp4"

    with pytest.raises(RuntimeError, match="Could not open video file: .*missing.mp4"):
        frame_at(missing, 0.0)


def test_capture_released_when_consumer_stops_early():
    capture = mock.Mock()
    capture.isOpened.return_value = True
    capture.get.return_value = 25.0
    capture.read.return_value = (True, np.zeros((144, 256, 3), dtype=np.uint8))

    with mock.patch("cv2.VideoCapture", return_value=capture):
        frames = sample_frames("fake.mp4")
        next(frames)
        frames.close()

    capture.release.assert_called_once()


def test_zero_native_fps_falls_back_to_requested_fps():
    capture = mock.Mock()
    capture.isOpened.return_value = True
    capture.get.return_value = 0.0
    frame = np.zeros((144, 256, 3), dtype=np.uint8)
    capture.read.side_effect = [(True, frame)] * 3 + [(False, None)]

    with mock.patch("cv2.VideoCapture", return_value=capture):
        samples = [(index, timestamp) for index, timestamp, _ in sample_frames("fake.mp4", fps=2.0)]

    assert samples == [(0, 0.0), (1, 0.5), (2, 1.0)]
    capture.release.assert_called_once()
