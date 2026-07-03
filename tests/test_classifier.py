"""Tests for hero/process heuristics at image and page level."""

import numpy as np

from compressor.classifier import (
    classify_image_array,
    classify_images,
    classify_page_array,
    colorfulness,
)
from compressor.pdf_io import open_pdf, scan_pdf
from compressor.schemas import PageType


def _noise_rgb(h: int, w: int, seed: int = 7) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 256, size=(h, w, 3), dtype=np.uint8)


def _line_art(h: int = 400, w: int = 400) -> np.ndarray:
    arr = np.full((h, w, 3), 255, dtype=np.uint8)
    arr[::10, :, :] = 40  # dense horizontal strokes
    arr[:, ::10, :] = 40
    return arr


def test_colorfulness_orders_correctly() -> None:
    gray = np.full((64, 64, 3), 128, dtype=np.uint8)
    assert colorfulness(_noise_rgb(64, 64)) > colorfulness(gray)


def test_colorful_large_image_is_hero() -> None:
    label, confidence = classify_image_array(_noise_rgb(400, 400), display_ratio=0.5)
    assert label == PageType.HERO
    assert 0.5 <= confidence <= 1.0


def test_line_art_is_process() -> None:
    label, confidence = classify_image_array(_line_art(), display_ratio=0.5)
    assert label == PageType.PROCESS
    assert confidence >= 0.5


def test_mostly_white_page_is_process() -> None:
    page = np.full((300, 220, 3), 255, dtype=np.uint8)
    page[40:60, 20:200] = 30  # a text block
    label, _ = classify_page_array(page)
    assert label == PageType.PROCESS


def test_full_bleed_colorful_page_is_hero() -> None:
    label, _ = classify_page_array(_noise_rgb(300, 220))
    assert label == PageType.HERO


def test_classify_images_labels_all(portfolio_pdf) -> None:
    doc = open_pdf(portfolio_pdf)
    images = scan_pdf(doc)
    classify_images(images)
    assert all(i.classification in (PageType.HERO, PageType.PROCESS) for i in images)
    assert all(0 < i.confidence <= 1 for i in images)
    # the big noise photos should classify as hero
    photos = [i for i in images if i.display_ratio > 0.3]
    assert photos and all(i.classification == PageType.HERO for i in photos)
    doc.close()
