"""v2 path: vector-preserving compression (recompress embedded images only).

Keeps text and line art as vectors. Per-image byte budgets are allocated by
classification and display size, then each image is fit to its budget by
first capping PPI, then binary-searching JPEG quality. A global adjust loop
rescales budgets until the whole file lands inside the target window.

Every round re-reads ImageInfo.original_data (cached at scan time), never
the already-compressed stream (pitfall 5).
"""

import io

import fitz
from PIL import Image

from compressor import config
from compressor.exceptions import CompressionError
from compressor.pdf_io import flatten_to_rgb, pdf_bytes
from compressor.schemas import CompressionConfig, ImageInfo, PageType


def _size_weight(display_ratio: float, cfg: CompressionConfig) -> float:
    if display_ratio >= config.LARGE_DISPLAY_RATIO:
        return cfg.large_size_weight
    if display_ratio >= config.MEDIUM_DISPLAY_RATIO:
        return cfg.medium_size_weight
    return cfg.small_size_weight


def _label_weight(page_type: PageType, cfg: CompressionConfig) -> float:
    return (
        cfg.hero_label_weight
        if page_type == PageType.HERO
        else cfg.process_label_weight
    )


def allocate_budgets(
    images: list[ImageInfo], image_budget: int, cfg: CompressionConfig
) -> dict[int, int]:
    """Split the image byte budget across images by weight x original size."""
    scores = {
        info.xref: _label_weight(info.classification, cfg)
        * _size_weight(info.display_ratio, cfg)
        * info.original_bytes
        for info in images
    }
    total = sum(scores.values()) or 1.0
    return {
        xref: max(int(image_budget * score / total), 1)
        for xref, score in scores.items()
    }


def _encode_jpeg(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def _ppi_ladder(info: ImageInfo, cfg: CompressionConfig) -> list[float]:
    """Candidate PPI values from the capped maximum down to the class minimum."""
    min_ppi = (
        cfg.hero_min_ppi
        if info.classification == PageType.HERO
        else cfg.process_min_ppi
    )
    top = min(cfg.max_ppi, info.effective_ppi)
    if top <= min_ppi:
        return [top]
    steps = 4
    ratio = (min_ppi / top) ** (1 / (steps - 1))
    return [top * ratio**i for i in range(steps)]


def compress_image(
    info: ImageInfo, budget: int, cfg: CompressionConfig
) -> tuple[bytes, int, int, bool]:
    """Fit one image into its byte budget.

    Returns (jpeg_bytes, new_width, new_height, quality_maxed) where
    quality_maxed means the result is already at the class quality ceiling
    at full allowed PPI, so more budget would not improve it.
    """
    hero = info.classification == PageType.HERO
    max_q = cfg.hero_max_quality if hero else cfg.process_max_quality
    min_q = cfg.hero_min_quality if hero else cfg.process_min_quality

    source = flatten_to_rgb(info)
    last: tuple[Image.Image, int, int] | None = None

    for ppi in _ppi_ladder(info, cfg):
        scale = min(ppi / max(info.effective_ppi, 1.0), 1.0)
        w = max(int(info.pixel_width * scale), 8)
        h = max(int(info.pixel_height * scale), 8)
        img = source.resize((w, h), Image.LANCZOS) if (w, h) != source.size else source

        data = _encode_jpeg(img, max_q)
        if len(data) <= budget:
            return data, w, h, True

        lo, hi = min_q, max_q
        candidate: bytes | None = None
        for _ in range(cfg.max_iterations_per_image):
            mid = (lo + hi) // 2
            data = _encode_jpeg(img, mid)
            if len(data) <= budget:
                candidate = data
                lo = mid + 1
            else:
                hi = mid - 1
            if lo > hi:
                break
        if candidate is not None:
            return candidate, w, h, False
        last = (img, w, h)

    if last is None:
        raise CompressionError(f"image xref={info.xref}: could not encode")
    img, w, h = last
    floor_q = min(cfg.small_image_quality_floor, min_q)
    return _encode_jpeg(img, floor_q), w, h, False


def write_image(
    doc: fitz.Document, info: ImageInfo, data: bytes, w: int, h: int
) -> None:
    """Replace the image stream and keep the PDF object metadata in sync.

    update_stream only swaps the bytes; Width/Height/Filter/ColorSpace must
    be updated explicitly (pitfall 2) and the SMask reference dropped after
    flattening transparency (pitfall 3).
    """
    doc.update_stream(info.xref, data, compress=False)
    doc.xref_set_key(info.xref, "Width", str(w))
    doc.xref_set_key(info.xref, "Height", str(h))
    doc.xref_set_key(info.xref, "Filter", "/DCTDecode")
    doc.xref_set_key(info.xref, "ColorSpace", "/DeviceRGB")
    doc.xref_set_key(info.xref, "BitsPerComponent", "8")
    doc.xref_set_key(info.xref, "DecodeParms", "null")
    doc.xref_set_key(info.xref, "Decode", "null")
    if info.smask_xref:
        doc.xref_set_key(info.xref, "SMask", "null")


def compress_v2(
    doc: fitz.Document, images: list[ImageInfo], cfg: CompressionConfig
) -> tuple[bytes, bool]:
    """Run the vector-preserving path. Returns (pdf_bytes, quality_maxed).

    Raises CompressionError when the non-image overhead alone exceeds the
    target (physical limit, pitfall 6) or the adjust loop cannot land under
    the target — the pipeline then falls back to the v1 path.
    """
    target = cfg.target_bytes
    tolerance = cfg.tolerance_bytes

    baseline = len(pdf_bytes(doc, cfg))
    if not images:
        if baseline <= target:
            return pdf_bytes(doc, cfg), True
        raise CompressionError("no compressible images and file exceeds target")

    overhead = baseline - sum(
        info.original_bytes + len(info.original_smask_data) for info in images
    )
    overhead = max(overhead, 0)
    image_budget = target - overhead - tolerance // 2
    if image_budget < len(images) * 1024:
        raise CompressionError(
            f"non-image overhead ~{overhead} bytes leaves no image budget for target {target}"
        )

    budgets = allocate_budgets(images, image_budget, cfg)
    scale = 1.0
    result: bytes | None = None

    for _ in range(cfg.max_global_adjust_rounds):
        written_total = 0
        all_maxed = True
        for info in images:
            budget = max(int(budgets[info.xref] * scale), 1024)
            data, w, h, maxed = compress_image(info, budget, cfg)
            write_image(doc, info, data, w, h)
            written_total += len(data)
            all_maxed = all_maxed and maxed

        result = pdf_bytes(doc, cfg)
        size = len(result)
        if target - tolerance <= size <= target:
            return result, False
        if size <= target and all_maxed:
            return result, True

        overhead_now = max(size - written_total, 0)
        wanted = target - tolerance // 2 - overhead_now
        if wanted <= 0:
            raise CompressionError(
                "non-image overhead exceeds target after compression"
            )
        scale = max(min(scale * wanted / max(written_total, 1), 8.0), 0.02)

    if result is not None and len(result) <= target:
        return result, False
    raise CompressionError("v2 global adjust could not reach the target size")
