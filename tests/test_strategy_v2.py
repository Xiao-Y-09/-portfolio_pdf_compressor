"""Tests for the vector-preserving (image-level) compression path."""

import fitz
import pytest

from compressor.classifier import classify_images
from compressor.exceptions import CompressionError
from compressor.pdf_io import open_pdf, scan_pdf
from compressor.schemas import CompressionConfig, ImageInfo, PageType
from compressor.strategy_v2 import (
    allocate_budgets,
    compress_image,
    compress_v2,
    write_image,
)


def _info(
    xref: int, label: PageType, display_ratio: float, nbytes: int = 100_000
) -> ImageInfo:
    return ImageInfo(
        xref=xref,
        page_num=0,
        original_bytes=nbytes,
        pixel_width=800,
        pixel_height=600,
        format="jpeg",
        display_rect=(0, 0, 400, 300),
        display_ratio=display_ratio,
        effective_ppi=144.0,
        classification=label,
    )


def test_allocate_budgets_prefers_hero() -> None:
    cfg = CompressionConfig(target_size_mb=5)
    hero = _info(1, PageType.HERO, 0.6)
    process = _info(2, PageType.PROCESS, 0.6)
    budgets = allocate_budgets([hero, process], 1_000_000, cfg)
    assert budgets[1] > budgets[2]
    assert sum(budgets.values()) <= 1_000_000 + 2


def test_allocate_budgets_prefers_large_display() -> None:
    cfg = CompressionConfig(target_size_mb=5)
    large = _info(1, PageType.HERO, 0.8)
    small = _info(2, PageType.HERO, 0.05)
    budgets = allocate_budgets([large, small], 1_000_000, cfg)
    assert budgets[1] > budgets[2]


def test_compress_image_respects_budget(portfolio_pdf) -> None:
    cfg = CompressionConfig(target_size_mb=5)
    doc = open_pdf(portfolio_pdf)
    info = max(scan_pdf(doc), key=lambda i: i.original_bytes)
    classify_images([info])
    budget = info.original_bytes // 4
    data, w, h, _ = compress_image(info, budget, cfg)
    assert len(data) <= budget
    assert 0 < w <= info.pixel_width
    assert 0 < h <= info.pixel_height
    doc.close()


def test_write_image_syncs_metadata(portfolio_pdf) -> None:
    cfg = CompressionConfig(target_size_mb=5)
    doc = open_pdf(portfolio_pdf)
    info = next(i for i in scan_pdf(doc) if i.smask_xref)
    classify_images([info])
    data, w, h, _ = compress_image(info, info.original_bytes, cfg)
    write_image(doc, info, data, w, h)

    assert doc.xref_get_key(info.xref, "Width")[1] == str(w)
    assert doc.xref_get_key(info.xref, "Height")[1] == str(h)
    assert doc.xref_get_key(info.xref, "SMask")[0] == "null"

    # the document must still round-trip and decode the replaced image
    rebuilt = fitz.open("pdf", doc.tobytes(garbage=4, deflate=True, clean=True))
    extracted = rebuilt.extract_image(rebuilt[0].get_images(full=True)[0][0])
    assert extracted["image"]
    rebuilt.close()
    doc.close()


def test_compress_v2_hits_target(portfolio_pdf) -> None:
    cfg = CompressionConfig(target_size_mb=3.0)
    doc = open_pdf(portfolio_pdf)
    original = portfolio_pdf.stat().st_size
    assert original > cfg.target_bytes, "fixture must need actual compression"

    images = scan_pdf(doc)
    classify_images(images)
    data, quality_maxed = compress_v2(doc, images, cfg)

    assert len(data) <= cfg.target_bytes
    if not quality_maxed:
        assert len(data) >= cfg.target_bytes - cfg.tolerance_bytes

    out = fitz.open("pdf", data)
    assert out.page_count == doc.page_count
    # every page must still render without raising
    for page in out:
        page.get_pixmap(dpi=36)
    out.close()
    doc.close()


def test_compress_v2_raises_when_overhead_exceeds_target(portfolio_pdf) -> None:
    cfg = CompressionConfig(target_size_mb=0.01)  # 10 KB: impossible for this file
    doc = open_pdf(portfolio_pdf)
    images = scan_pdf(doc)
    classify_images(images)
    with pytest.raises(CompressionError):
        compress_v2(doc, images, cfg)
    doc.close()
