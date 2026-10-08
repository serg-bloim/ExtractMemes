import cv2
import numpy as np
import pytest

from tools.labeling import similarity


def test_expand_grows_while_the_step_stays_below_the_cut_and_stops_at_a_cut():
    levels = [0] * 10 + [100, 130, 100, 130, 100] + [0] * 10          # a flickering card in a static scene
    describe = lambda i: np.full((18, 32), levels[i], np.float32)

    assert similarity.expand(12, 12, len(levels), describe, max_frames=50) == (10, 14)
    assert similarity.expand(10, 14, len(levels), describe, max_frames=50) == (10, 14)   # already the whole card
    assert similarity.expand(2, 2, len(levels), describe, max_frames=50) == (0, 9)       # static: up to the cut / the ends


def test_expand_is_capped_per_side_and_stays_inside_the_video():
    describe = lambda i: np.zeros((18, 32), np.float32)
    assert similarity.expand(20, 22, 100, describe, max_frames=5) == (15, 27)
    assert similarity.expand(1, 1, 4, describe, max_frames=50) == (0, 3)


def test_descriptor_is_a_small_grayscale_thumbnail():
    frame = np.full((72, 128, 3), 90, np.uint8)
    d = similarity.descriptor(frame)
    assert d.shape == (18, 32) and d.dtype == np.float32 and d.mean() == pytest.approx(90, abs=1)
    assert similarity.step(d, d + 7) == pytest.approx(7)
