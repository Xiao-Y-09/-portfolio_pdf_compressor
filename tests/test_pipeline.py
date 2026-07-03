"""End-to-end tests: strategy switching and target window compliance."""

from pathlib import Path

import fitz
import pytest

from compressor.pipeline import choose_strategy, compress_pdf
from compressor.schemas import CompressionConfig, Strategy


def test_choose_strategy_thresholds() -> None:
    cfg = CompressionConfig(target_size_mb=4.0)  # 4 MB target
    mb = 1024 * 1024
    assert choose_strategy(3 * mb, cfg) == Strategy.PASSTHROUGH
    assert choose_strategy(8 * mb, cfg) == Strategy.VECTOR_PRESERVING  # ratio 0.5
    assert choose_strategy(20 * mb, cfg) == Strategy.PAGE_RASTERIZATION  # ratio 0.2


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
    target_mb = original * 0.6 / (1024 * 1024)  # ratio 0.6 -> v2
    out = tmp_path / "gentle.pdf"

    result = compress_pdf(portfolio_pdf, target_mb, out)

    assert result.strategy == Strategy.VECTOR_PRESERVING
    assert result.output_bytes <= result.target_bytes
    if not result.quality_maxed:
        assert result.output_bytes >= result.target_bytes - int(0.3 * 1024 * 1024)
    src = fitz.open(str(portfolio_pdf))
    _check_output(out, result.target_bytes, src.page_count)
    src.close()


def test_aggressive_ratio_uses_v1(portfolio_pdf: Path, tmp_path: Path) -> None:
    original = portfolio_pdf.stat().st_size
    target_mb = original * 0.2 / (1024 * 1024)  # ratio 0.2 -> v1
    out = tmp_path / "aggressive.pdf"

    result = compress_pdf(portfolio_pdf, target_mb, out)

    assert result.strategy == Strategy.PAGE_RASTERIZATION
    assert result.output_bytes <= result.target_bytes
    src = fitz.open(str(portfolio_pdf))
    _check_output(out, result.target_bytes, src.page_count)
    src.close()


def test_passthrough_when_already_small(small_pdf: Path, tmp_path: Path) -> None:
    out = tmp_path / "passthrough.pdf"
    result = compress_pdf(small_pdf, 5.0, out)
    assert result.strategy == Strategy.PASSTHROUGH
    assert out.stat().st_size <= result.target_bytes


def test_default_output_path(portfolio_pdf: Path, tmp_path: Path) -> None:
    src = tmp_path / "mywork.pdf"
    src.write_bytes(portfolio_pdf.read_bytes())
    result = compress_pdf(src, src.stat().st_size * 0.6 / (1024 * 1024))
    expected = tmp_path / "mywork_compressed.pdf"
    assert expected.is_file()
    assert result.output_bytes == expected.stat().st_size


def test_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        compress_pdf(tmp_path / "nope.pdf", 5.0)
