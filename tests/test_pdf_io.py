"""Tests for scanning, extraction and size measurement."""

from pathlib import Path

import fitz
import pytest

from compressor import config
from compressor.exceptions import PDFParseError
from compressor.pdf_io import (
    decode_image,
    flatten_to_rgb,
    open_pdf,
    pdf_bytes,
    scan_pdf,
)
from compressor.schemas import CompressionConfig


def test_open_pdf_rejects_garbage(tmp_path: Path) -> None:
    bogus = tmp_path / "bogus.pdf"
    bogus.write_bytes(b"not a pdf at all")
    with pytest.raises(PDFParseError):
        open_pdf(bogus)


def test_scan_finds_large_images_and_skips_tiny(portfolio_pdf: Path) -> None:
    doc = open_pdf(portfolio_pdf)
    images = scan_pdf(doc)
    # 4 noise photos + 1 RGBA image; the 20x20 icon must be filtered out
    assert len(images) == 5
    for info in images:
        assert info.pixel_width * info.pixel_height >= config.MIN_IMAGE_PIXEL_AREA
        assert info.original_bytes >= config.MIN_IMAGE_BYTES
        assert info.original_data
        assert info.effective_ppi > 0
        assert 0 < info.display_ratio <= 1
    doc.close()


def test_scan_captures_smask(portfolio_pdf: Path) -> None:
    doc = open_pdf(portfolio_pdf)
    images = scan_pdf(doc)
    with_smask = [i for i in images if i.smask_xref]
    assert len(with_smask) == 1
    assert with_smask[0].original_smask_data
    doc.close()


def test_decode_image_caps_dimension(portfolio_pdf: Path) -> None:
    doc = open_pdf(portfolio_pdf)
    info = max(scan_pdf(doc), key=lambda i: i.pixel_width)
    arr = decode_image(info, max_dim=256)
    assert max(arr.shape[:2]) <= 256
    assert arr.shape[2] == 3
    doc.close()


def test_flatten_to_rgb_composites_alpha(portfolio_pdf: Path) -> None:
    doc = open_pdf(portfolio_pdf)
    info = next(i for i in scan_pdf(doc) if i.smask_xref)
    img = flatten_to_rgb(info)
    assert img.mode == "RGB"
    # left column of the fixture gradient mask is fully transparent -> white
    assert img.getpixel((0, 0)) == (255, 255, 255)
    doc.close()


def test_pdf_bytes_uses_garbage_collection(portfolio_pdf: Path) -> None:
    cfg = CompressionConfig(target_size_mb=5)
    doc = open_pdf(portfolio_pdf)
    measured = len(pdf_bytes(doc, cfg))
    on_disk = portfolio_pdf.stat().st_size
    assert measured == pytest.approx(on_disk, rel=0.05)
    doc.close()


def test_scan_skips_non_stream_xrefs() -> None:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "no images here")
    assert scan_pdf(doc) == []
    doc.close()
