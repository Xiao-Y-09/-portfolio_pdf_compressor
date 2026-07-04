"""Tests for the vector-preserving (image-level) compression path."""

import io

import fitz
import numpy as np
import pytest
from PIL import Image

from compressor import config
from compressor.classifier import classify_images
from compressor.exceptions import CompressionError
from compressor.pdf_io import open_pdf, scan_pdf
from compressor.schemas import CompressionConfig, ImageInfo, PageType
from compressor.strategy_v2 import (
    allocate_budgets,
    apply_page_selection,
    compress_image,
    compress_v2,
    encode_image,
    is_grayscale_image,
    quality_to_j2k_rate,
    write_image,
)
from conftest import gray_jpeg

JP2_SIGNATURE = bytes.fromhex("0000000c6a5020200d0a870a")


def _cfg(target_mb: float = 5.0) -> CompressionConfig:
    return CompressionConfig(target_size_mb=target_mb)


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
    cfg = _cfg()
    hero = _info(1, PageType.HERO, 0.6)
    process = _info(2, PageType.PROCESS, 0.6)
    budgets = allocate_budgets([hero, process], 1_000_000, cfg)
    assert budgets[1] > budgets[2]
    assert sum(budgets.values()) <= 1_000_000 + 2


def test_allocate_budgets_prefers_large_display() -> None:
    cfg = _cfg()
    large = _info(1, PageType.HERO, 0.8)
    small = _info(2, PageType.HERO, 0.05)
    budgets = allocate_budgets([large, small], 1_000_000, cfg)
    assert budgets[1] > budgets[2]


def test_apply_page_selection_overrides_ai() -> None:
    images = [_info(1, PageType.PROCESS, 0.5), _info(2, PageType.HERO, 0.5)]
    images[1].page_num = 3
    apply_page_selection(images, selected_pages={0})
    assert images[0].classification == PageType.HERO  # page 0 selected
    assert images[1].classification == PageType.PROCESS  # page 3 not selected


def test_is_grayscale_image() -> None:
    rng = np.random.default_rng(1)
    gray = Image.fromarray(rng.integers(0, 256, size=(64, 64), dtype=np.uint8)).convert(
        "RGB"
    )
    color = Image.fromarray(rng.integers(0, 256, size=(64, 64, 3), dtype=np.uint8))
    assert is_grayscale_image(gray, threshold=5)
    assert not is_grayscale_image(color, threshold=5)


def test_quality_to_j2k_rate_grows_as_quality_drops() -> None:
    cfg = _cfg()
    at_threshold = quality_to_j2k_rate(cfg.jpeg2000_quality_threshold, cfg)
    assert at_threshold == config.J2K_RATE_AT_THRESHOLD
    assert quality_to_j2k_rate(20, cfg) > at_threshold
    assert quality_to_j2k_rate(10, cfg) > quality_to_j2k_rate(20, cfg)


def test_encode_image_switches_format_at_threshold() -> None:
    cfg = _cfg()
    img = Image.fromarray(
        np.random.default_rng(2).integers(0, 256, size=(200, 200, 3), dtype=np.uint8)
    )
    jpeg_data, jpeg_filter = encode_image(img, cfg.jpeg2000_quality_threshold, cfg)
    j2k_data, j2k_filter = encode_image(img, cfg.jpeg2000_quality_threshold - 1, cfg)
    assert jpeg_filter == "/DCTDecode" and jpeg_data.startswith(b"\xff\xd8")
    assert j2k_filter == "/JPXDecode" and j2k_data.startswith(JP2_SIGNATURE)


def test_compress_image_grayscale_goes_single_channel() -> None:
    data = gray_jpeg(800, 600)
    info = _info(1, PageType.HERO, 0.5, nbytes=len(data))
    info.original_data = data
    encoded = compress_image(info, budget=len(data), cfg=_cfg())
    assert encoded.colorspace == "/DeviceGray"
    # a colorful image must stay RGB
    color_info = _info(2, PageType.HERO, 0.5)
    arr = np.random.default_rng(3).integers(0, 256, size=(600, 800, 3), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="JPEG", quality=95)
    color_info.original_data = buf.getvalue()
    encoded_color = compress_image(color_info, budget=10**7, cfg=_cfg())
    assert encoded_color.colorspace == "/DeviceRGB"


def test_compress_image_respects_budget(portfolio_pdf) -> None:
    cfg = _cfg()
    doc = open_pdf(portfolio_pdf)
    info = max(scan_pdf(doc), key=lambda i: i.original_bytes)
    classify_images([info])
    budget = info.original_bytes // 4
    encoded = compress_image(info, budget, cfg)
    assert len(encoded.data) <= budget
    assert 0 < encoded.width <= info.pixel_width
    assert 0 < encoded.height <= info.pixel_height
    doc.close()


def test_write_image_syncs_metadata(portfolio_pdf) -> None:
    cfg = _cfg()
    doc = open_pdf(portfolio_pdf)
    info = next(i for i in scan_pdf(doc) if i.smask_xref)
    classify_images([info])
    encoded = compress_image(info, info.original_bytes, cfg)
    write_image(doc, info, encoded)

    assert doc.xref_get_key(info.xref, "Width")[1] == str(encoded.width)
    assert doc.xref_get_key(info.xref, "Height")[1] == str(encoded.height)
    assert doc.xref_get_key(info.xref, "Filter")[1].lstrip(
        "/"
    ) == encoded.pdf_filter.lstrip("/")
    assert doc.xref_get_key(info.xref, "SMask")[0] == "null"

    # the document must still round-trip and decode the replaced image
    rebuilt = fitz.open("pdf", doc.tobytes(garbage=4, deflate=True, clean=True))
    extracted = rebuilt.extract_image(rebuilt[0].get_images(full=True)[0][0])
    assert extracted["image"]
    rebuilt.close()
    doc.close()


def test_compress_v2_hits_target(portfolio_pdf) -> None:
    cfg = _cfg(3.0)
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
    for page in out:
        page.get_pixmap(dpi=36)
    out.close()
    doc.close()


def test_compress_v2_selected_pages_shift_budget(portfolio_pdf) -> None:
    """Selecting a page must give its images a larger share of the budget."""
    cfg = _cfg(2.0)

    def image_bytes_on_page(selected: set[int], page: int) -> int:
        doc = open_pdf(portfolio_pdf)
        images = scan_pdf(doc)
        data, _ = compress_v2(doc, images, cfg, selected_pages=selected)
        doc.close()
        out = fitz.open("pdf", data)
        total = 0
        for entry in out[page].get_images(full=True):
            total += len(out.xref_stream_raw(entry[0]) or b"")
        out.close()
        return total

    favored = image_bytes_on_page(selected={1}, page=1)
    unfavored = image_bytes_on_page(selected={2}, page=1)
    assert favored > unfavored


def test_compress_v2_raises_when_overhead_exceeds_target(portfolio_pdf) -> None:
    cfg = _cfg(0.01)  # 10 KB: impossible for this file
    doc = open_pdf(portfolio_pdf)
    images = scan_pdf(doc)
    classify_images(images)
    with pytest.raises(CompressionError):
        compress_v2(doc, images, cfg)
    doc.close()
