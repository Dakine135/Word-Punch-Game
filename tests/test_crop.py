import numpy as np

from word_punch.vision.service import crop_to_aspect


def test_4_3_frame_cropped_to_16_9_keeps_full_width():
    img = np.zeros((480, 640, 3), np.uint8)
    out = crop_to_aspect(img, 16 / 9)
    assert out.shape[1] == 640 and abs(out.shape[1] / out.shape[0] - 16 / 9) < 0.01


def test_wide_frame_trims_sides():
    out = crop_to_aspect(np.zeros((360, 900, 3), np.uint8), 16 / 9)
    assert out.shape[0] == 360 and out.shape[1] == 640


def test_matching_aspect_untouched():
    img = np.zeros((360, 640, 3), np.uint8)
    assert crop_to_aspect(img, 16 / 9) is img
