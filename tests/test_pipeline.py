"""End-to-end tests: analysis phase, strategy switching, target compliance."""

import base64
from pathlib import Path

import fitz
import pytest

from compressor.pdf_io import open_pdf, pdf_bytes
from compressor.pipeline import (
    _subset_fonts,
    choose_strategy,
    run_analysis,
    run_compression,
)
from compressor.schemas import CompressionConfig, PageType, Strategy

MB = 1024 * 1024


def test_choose_strategy_thresholds() -> None:
    cfg = CompressionConfig(target_size_mb=4.0)
    assert choose_strategy(3 * MB, cfg) == Strategy.PASSTHROUGH
    # v4: vector preserving is the default almost everywhere
    assert choose_strategy(8 * MB, cfg) == Strategy.VECTOR_PRESERVING  # ratio 0.5
    assert choose_strategy(20 * MB, cfg) == Strategy.VECTOR_PRESERVING  # ratio 0.2
    assert choose_strategy(100 * MB, cfg) == Strategy.PAGE_RASTERIZATION  # ratio 0.04


def test_run_analysis_structure(portfolio_pdf: Path) -> None:
    analysis = run_analysis(portfolio_pdf)
    assert analysis.page_count == 4
    assert len(analysis.thumbnails) == 4
    assert len(analysis.page_classifications) == 4
    assert analysis.original_size_mb > 0
    # thumbnails are valid base64-encoded JPEGs
    decoded = base64.b64decode(analysis.thumbnails[0])
    assert decoded.startswith(b"\xff\xd8")
    # suggested pages are 1-indexed and match hero classifications
    heroes = [
        i + 1
        for i, label in enumerate(analysis.page_classifications)
        if label == PageType.HERO
    ]
    assert analysis.ai_suggested_pages == heroes


def test_font_subsetting_shrinks_embedded_fonts(embedded_font_pdf: Path) -> None:
    cfg = CompressionConfig(target_size_mb=5.0)
    doc = open_pdf(embedded_font_pdf)
    before = len(pdf_bytes(doc, cfg))
    _subset_fonts(doc, cfg)
    after = len(pdf_bytes(doc, cfg))
    doc.close()
    assert after < before


def _check_output(path: Path, target_bytes: int, expected_pages: int) -> None:
    size = path.stat().st_size
    assert size <= target_bytes
    doc = fitz.open(str(path))
    assert doc.page_count == expected_pages
    for page in doc:
        page.get_pixmap(dpi=36)
    doc.close()


def test_gentle_ratio_uses_v2(portfolio_pdf: Path, tmp_path: Path) -> None:
    original = portfolio_pdf.stat().st_size
    target_mb = original * 0.6 / MB
    out = tmp_path / "gentle.pdf"

    result = run_compression(portfolio_pdf, target_mb, output_path=out)

    assert result.strategy == Strategy.VECTOR_PRESERVING
    assert result.output_bytes <= result.target_bytes
    if not result.quality_maxed:
        assert result.output_bytes >= result.target_bytes - int(0.3 * MB)
    src = fitz.open(str(portfolio_pdf))
    _check_output(out, result.target_bytes, src.page_count)
    src.close()


def test_selected_pages_reach_target(portfolio_pdf: Path, tmp_path: Path) -> None:
    original = portfolio_pdf.stat().st_size
    target_mb = original * 0.4 / MB
    out = tmp_path / "reviewed.pdf"

    result = run_compression(
        portfolio_pdf, target_mb, selected_pages=[1, 3], output_path=out
    )

    assert result.strategy == Strategy.VECTOR_PRESERVING
    assert result.output_bytes <= result.target_bytes
    src = fitz.open(str(portfolio_pdf))
    _check_output(out, result.target_bytes, src.page_count)
    src.close()


def test_extreme_ratio_uses_v1(portfolio_pdf: Path, tmp_path: Path) -> None:
    """With a raised switch ratio, an aggressive target selects rasterization."""
    original = portfolio_pdf.stat().st_size
    target_mb = original * 0.2 / MB
    cfg = CompressionConfig(target_size_mb=target_mb, strategy_switch_ratio=0.4)
    out = tmp_path / "extreme.pdf"

    result = run_compression(portfolio_pdf, target_mb, output_path=out, cfg=cfg)

    assert result.strategy == Strategy.PAGE_RASTERIZATION
    assert result.output_bytes <= result.target_bytes
    src = fitz.open(str(portfolio_pdf))
    _check_output(out, result.target_bytes, src.page_count)
    src.close()


def test_passthrough_when_already_small(small_pdf: Path, tmp_path: Path) -> None:
    out = tmp_path / "passthrough.pdf"
    result = run_compression(small_pdf, 5.0, output_path=out)
    assert result.strategy == Strategy.PASSTHROUGH
    assert out.stat().st_size <= result.target_bytes


def test_default_output_path(portfolio_pdf: Path, tmp_path: Path) -> None:
    src = tmp_path / "mywork.pdf"
    src.write_bytes(portfolio_pdf.read_bytes())
    result = run_compression(src, src.stat().st_size * 0.6 / MB)
    expected = tmp_path / "mywork_compressed.pdf"
    assert expected.is_file()
    assert result.output_bytes == expected.stat().st_size


def test_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        run_compression(tmp_path / "nope.pdf", 5.0)
