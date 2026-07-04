"""v2 path: vector-preserving compression (recompress embedded images only).

Keeps text and line art as vectors. Per-image byte budgets are allocated by
classification and display size, then each image is fit to its budget by
first capping PPI, then binary-searching quality. A global adjust loop
rescales budgets until the whole file lands inside the target window.

v4 additions:
- near-grayscale images are stored single-channel (saves ~66%)
- quality below cfg.jpeg2000_quality_threshold encodes as JPEG 2000 to avoid
  block artifacts (pitfall 8: J2K takes a compression rate, not a quality)
- user-reviewed selected_pages override the AI hero/process classification

Every round re-reads ImageInfo.original_data (cached at scan time), never
the already-compressed stream (pitfall 5).
"""

import io

import fitz
import numpy as np
from PIL import Image
from pydantic import BaseModel

from compressor import config
from compressor.exceptions import CompressionError
from compressor.pdf_io import flatten_to_rgb, pdf_bytes
from compressor.schemas import CompressionConfig, ImageInfo, PageType


class EncodedImage(BaseModel):
    """One re-encoded image plus the PDF keys its object must carry."""

    data: bytes
    width: int
    height: int
    quality_maxed: bool
    pdf_filter: str  # "/DCTDecode" or "/JPXDecode"
    colorspace: str  # "/DeviceRGB" or "/DeviceGray"


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


def apply_page_selection(images: list[ImageInfo], selected_pages: set[int]) -> None:
    """Override AI classification with the user's page review (0-indexed pages)."""
    for info in images:
        if info.page_num in selected_pages:
            info.classification = PageType.HERO
        else:
            info.classification = PageType.PROCESS
        info.confidence = 1.0


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


def is_grayscale_image(img: Image.Image, threshold: int) -> bool:
    """True when the RGB channels are near-identical across the image."""
    probe = img
    if max(probe.size) > 256:
        probe = probe.copy()
        probe.thumbnail((256, 256), Image.BILINEAR)
    arr = np.asarray(probe.convert("RGB"), dtype=np.int16)
    spread = arr.max(axis=-1) - arr.min(axis=-1)
    return float(np.percentile(spread, 99)) <= threshold


def quality_to_j2k_rate(quality: int, cfg: CompressionConfig) -> float:
    """Map a JPEG-style quality to a JPEG 2000 compression rate (pitfall 8)."""
    below = max(cfg.jpeg2000_quality_threshold - quality, 0)
    return config.J2K_RATE_AT_THRESHOLD + below * config.J2K_RATE_SLOPE


def encode_image(
    img: Image.Image, quality: int, cfg: CompressionConfig
) -> tuple[bytes, str]:
    """Encode at the given quality; returns (bytes, pdf_filter).

    quality < cfg.jpeg2000_quality_threshold uses JPEG 2000 (/JPXDecode),
    anything above uses baseline JPEG (/DCTDecode).
    """
    buf = io.BytesIO()
    if quality < cfg.jpeg2000_quality_threshold:
        img.save(
            buf,
            format="JPEG2000",
            quality_mode="rates",
            quality_layers=[quality_to_j2k_rate(quality, cfg)],
            irreversible=True,
        )
        return buf.getvalue(), "/JPXDecode"
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue(), "/DCTDecode"


def _ppi_ladder(info: ImageInfo, cfg: CompressionConfig) -> list[float]:
    """Candidate PPI values from the capped maximum down to the class minimum."""
    if info.classification == PageType.HERO:
        max_ppi, min_ppi = cfg.hero_max_ppi, cfg.hero_min_ppi
    else:
        max_ppi, min_ppi = cfg.process_max_ppi, cfg.process_min_ppi
    top = min(max_ppi, info.effective_ppi)
    if top <= min_ppi:
        return [top]
    steps = 4
    ratio = (min_ppi / top) ** (1 / (steps - 1))
    return [top * ratio**i for i in range(steps)]


def compress_image(
    info: ImageInfo, budget: int, cfg: CompressionConfig
) -> EncodedImage:
    """Fit one image into its byte budget.

    quality_maxed means the result is already at the class quality ceiling
    at full allowed PPI, so more budget would not improve it.
    """
    hero = info.classification == PageType.HERO
    max_q = cfg.hero_max_quality if hero else cfg.process_max_quality
    min_q = cfg.hero_min_quality if hero else cfg.process_min_quality

    source = flatten_to_rgb(info)
    if cfg.enable_grayscale_detection and is_grayscale_image(
        source, cfg.grayscale_channel_diff_threshold
    ):
        source = source.convert("L")
    colorspace = "/DeviceGray" if source.mode == "L" else "/DeviceRGB"

    last: tuple[Image.Image, int, int] | None = None

    for ppi in _ppi_ladder(info, cfg):
        scale = min(ppi / max(info.effective_ppi, 1.0), 1.0)
        w = max(int(info.pixel_width * scale), 8)
        h = max(int(info.pixel_height * scale), 8)
        img = source.resize((w, h), Image.LANCZOS) if (w, h) != source.size else source

        data, pdf_filter = encode_image(img, max_q, cfg)
        if len(data) <= budget:
            return EncodedImage(
                data=data,
                width=w,
                height=h,
                quality_maxed=True,
                pdf_filter=pdf_filter,
                colorspace=colorspace,
            )

        lo, hi = min_q, max_q
        candidate: tuple[bytes, str] | None = None
        for _ in range(cfg.max_iterations_per_image):
            mid = (lo + hi) // 2
            data, pdf_filter = encode_image(img, mid, cfg)
            if len(data) <= budget:
                candidate = (data, pdf_filter)
                lo = mid + 1
            else:
                hi = mid - 1
            if lo > hi:
                break
        if candidate is not None:
            return EncodedImage(
                data=candidate[0],
                width=w,
                height=h,
                quality_maxed=False,
                pdf_filter=candidate[1],
                colorspace=colorspace,
            )
        last = (img, w, h)

    if last is None:
        raise CompressionError(f"image xref={info.xref}: could not encode")
    img, w, h = last
    floor_q = min(cfg.small_image_quality_floor, min_q)
    data, pdf_filter = encode_image(img, floor_q, cfg)
    return EncodedImage(
        data=data,
        width=w,
        height=h,
        quality_maxed=False,
        pdf_filter=pdf_filter,
        colorspace=colorspace,
    )


def write_image(doc: fitz.Document, info: ImageInfo, encoded: EncodedImage) -> None:
    """Replace the image stream and keep the PDF object metadata in sync.

    update_stream only swaps the bytes; Width/Height/Filter/ColorSpace must
    be updated explicitly (pitfall 2) and the SMask reference dropped after
    flattening transparency (pitfall 3).
    """
    doc.update_stream(info.xref, encoded.data, compress=False)
    doc.xref_set_key(info.xref, "Width", str(encoded.width))
    doc.xref_set_key(info.xref, "Height", str(encoded.height))
    doc.xref_set_key(info.xref, "Filter", encoded.pdf_filter)
    doc.xref_set_key(info.xref, "ColorSpace", encoded.colorspace)
    doc.xref_set_key(info.xref, "BitsPerComponent", "8")
    doc.xref_set_key(info.xref, "DecodeParms", "null")
    doc.xref_set_key(info.xref, "Decode", "null")
    if info.smask_xref:
        doc.xref_set_key(info.xref, "SMask", "null")


def compress_v2(
    doc: fitz.Document,
    images: list[ImageInfo],
    cfg: CompressionConfig,
    selected_pages: set[int] | None = None,
) -> tuple[bytes, bool]:
    """Run the vector-preserving path. Returns (pdf_bytes, quality_maxed).

    selected_pages (0-indexed) comes from the user's review and overrides
    the AI classification; None keeps the AI labels.

    Raises CompressionError when the non-image overhead alone exceeds the
    target (physical limit) or the adjust loop cannot land under the
    target — the pipeline then falls back to the v1 path.
    """
    target = cfg.target_bytes
    tolerance = cfg.tolerance_bytes

    if selected_pages is not None:
        apply_page_selection(images, selected_pages)

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
            encoded = compress_image(info, budget, cfg)
            write_image(doc, info, encoded)
            written_total += len(encoded.data)
            all_maxed = all_maxed and encoded.quality_maxed

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
