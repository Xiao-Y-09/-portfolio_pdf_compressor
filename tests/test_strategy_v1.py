"""Tests for the whole-page rasterization path."""

import fitz

from compressor.classifier import classify_pages
from compressor.pdf_io import open_pdf
from compressor.schemas import CompressionConfig, PageType
from compressor.strategy_v1 import _page_quality, compress_v1


def test_page_quality_scales_and_clamps() -> None:
    cfg = CompressionConfig(target_size_mb=5)
    assert _page_quality(PageType.HERO, 1.0, cfg) == cfg.hero_base_quality
    assert _page_quality(PageType.HERO, 0.01, cfg) == cfg.hero_min_quality_v1
    assert _page_quality(PageType.PROCESS, 0.01, cfg) == cfg.process_min_quality_v1
    assert _page_quality(PageType.HERO, 1.0, cfg) > _page_quality(
        PageType.PROCESS, 1.0, cfg
    )


def test_compress_v1_hits_aggressive_target(portfolio_pdf) -> None:
    cfg = CompressionConfig(target_size_mb=1.0)
    doc = open_pdf(portfolio_pdf)
    pages = classify_pages(doc)
    data, quality_maxed = compress_v1(doc, pages, cfg)

    assert len(data) <= cfg.target_bytes
    if not quality_maxed:
        assert len(data) >= cfg.target_bytes - cfg.tolerance_bytes

    out = fitz.open("pdf", data)
    assert out.page_count == doc.page_count
    # rasterized pages keep the original geometry
    assert abs(out[0].rect.width - doc[0].rect.width) < 1
    assert abs(out[0].rect.height - doc[0].rect.height) < 1
    for page in out:
        page.get_pixmap(dpi=36)
    out.close()
    doc.close()


def test_compress_v1_page_count_preserved(portfolio_pdf) -> None:
    cfg = CompressionConfig(target_size_mb=2.0)
    doc = open_pdf(portfolio_pdf)
    pages = classify_pages(doc)
    assert len(pages) == doc.page_count
    data, _ = compress_v1(doc, pages, cfg)
    out = fitz.open("pdf", data)
    assert out.page_count == doc.page_count
    out.close()
    doc.close()
