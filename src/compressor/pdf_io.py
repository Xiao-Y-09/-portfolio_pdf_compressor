"""PDF scanning, image extraction and page rendering built on PyMuPDF.

All size measurements go through pdf_bytes() so that garbage collection is
always applied (pitfall 4). scan_pdf() caches each image's original bytes so
later rounds never recompress an already-compressed image (pitfall 5).
"""

import io
from pathlib import Path

import fitz
import numpy as np
from PIL import Image

from compressor import config
from compressor.exceptions import PDFParseError
from compressor.schemas import CompressionConfig, ImageInfo


def open_pdf(path: str | Path) -> fitz.Document:
    """Open a PDF file, raising PDFParseError on any failure."""
    try:
        doc = fitz.open(str(path))
    except Exception as exc:
        raise PDFParseError(f"cannot open PDF: {path}: {exc}") from exc
    if not doc.is_pdf:
        doc.close()
        raise PDFParseError(f"not a PDF file: {path}")
    if doc.needs_pass:
        doc.close()
        raise PDFParseError(f"PDF is password-protected: {path}")
    return doc


def pdf_bytes(doc: fitz.Document, cfg: CompressionConfig) -> bytes:
    """Serialize with full garbage collection so sizes are trustworthy (pitfall 4).

    Garbage collection is run on a snapshot copy: tobytes(garbage=4) mutates
    the live document and renumbers its xrefs, which would break any cached
    xref numbers held by the caller.
    """
    snapshot = fitz.open("pdf", doc.tobytes())
    try:
        return snapshot.tobytes(
            garbage=cfg.garbage_level, deflate=cfg.deflate, clean=cfg.clean
        )
    finally:
        snapshot.close()


def scan_pdf(doc: fitz.Document) -> list[ImageInfo]:
    """Collect compressible embedded images with cached original data.

    Skips non-stream xrefs (pitfall 1), tiny decorative images (pitfall 7)
    and images that are never actually displayed on a page.
    """
    seen: dict[int, ImageInfo] = {}
    for page in doc:
        page_area = abs(page.rect) or 1.0
        for entry in page.get_images(full=True):
            xref, smask_xref = entry[0], entry[1]
            if xref <= 0 or not doc.xref_is_stream(xref):
                continue

            rects = page.get_image_rects(xref)
            if not rects:
                continue
            rect = max(rects, key=abs)
            display_ratio = min(abs(rect) / page_area, 1.0)

            if xref in seen:
                info = seen[xref]
                if display_ratio > info.display_ratio:
                    info.display_ratio = display_ratio
                    info.display_rect = (rect.x0, rect.y0, rect.x1, rect.y1)
                continue

            try:
                extracted = doc.extract_image(xref)
            except Exception:
                continue
            if not extracted or not extracted.get("image"):
                continue

            width = int(extracted.get("width", 0))
            height = int(extracted.get("height", 0))
            data = extracted["image"]
            raw_len = len(doc.xref_stream_raw(xref) or b"")
            if (
                width * height < config.MIN_IMAGE_PIXEL_AREA
                or raw_len < config.MIN_IMAGE_BYTES
            ):
                continue
            try:
                with Image.open(io.BytesIO(data)) as probe:
                    probe.size  # header-only check: skip formats Pillow cannot decode
            except Exception:
                continue

            smask_data = b""
            if smask_xref > 0 and doc.xref_is_stream(smask_xref):
                try:
                    smask_data = doc.extract_image(smask_xref).get("image", b"")
                except Exception:
                    smask_data = b""

            display_width_inches = max(rect.width, 1.0) / 72.0
            seen[xref] = ImageInfo(
                xref=xref,
                page_num=page.number,
                original_bytes=raw_len,
                original_data=data,
                original_ext=extracted.get("ext", "jpeg"),
                original_smask_data=smask_data,
                smask_xref=smask_xref if smask_data else 0,
                pixel_width=width,
                pixel_height=height,
                format=extracted.get("ext", ""),
                display_rect=(rect.x0, rect.y0, rect.x1, rect.y1),
                display_ratio=display_ratio,
                effective_ppi=width / display_width_inches,
            )
    return list(seen.values())


def decode_image(info: ImageInfo, max_dim: int = 0) -> np.ndarray:
    """Decode an ImageInfo's cached original data to an RGB numpy array.

    max_dim > 0 caps the long side (used by the classifier for speed).
    """
    with Image.open(io.BytesIO(info.original_data)) as img:
        img = img.convert("RGB")
        if max_dim and max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.LANCZOS)
        return np.asarray(img)


def flatten_to_rgb(info: ImageInfo) -> Image.Image:
    """Decode the original image and composite any transparency onto white.

    Used before JPEG re-encoding; the caller must also drop the SMask
    reference on the PDF object (pitfall 3).
    """
    img = Image.open(io.BytesIO(info.original_data))
    if info.original_smask_data:
        mask = Image.open(io.BytesIO(info.original_smask_data)).convert("L")
        if mask.size != img.size:
            mask = mask.resize(img.size, Image.LANCZOS)
        img = img.convert("RGB")
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=mask)
        return background
    if img.mode in ("RGBA", "LA", "PA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.getchannel("A"))
        return background
    return img.convert("RGB")


def render_page(page: fitz.Page, dpi: int) -> np.ndarray:
    """Render a page to an RGB numpy array at the given DPI."""
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8)
    return arr.reshape(pix.height, pix.width, 3).copy()
