"""v1 path: whole-page rasterization for aggressive compression ratios.

Each page is rendered once at the working DPI and cached as a high-quality
JPEG in memory. A global quality multiplier is then binary-searched: each
candidate rebuilds the output PDF by re-encoding every cached page at
quality = base_quality(page type) * multiplier, clamped to per-class bounds.
If even the lowest multiplier overshoots the target, the working DPI is
reduced and the pages re-rendered.
"""

import io

import fitz
from PIL import Image

from compressor import config
from compressor.exceptions import CompressionError
from compressor.pdf_io import render_page
from compressor.schemas import CompressionConfig, PageInfo, PageType

_CACHE_QUALITY = 95  # quality of the in-memory render cache


def _page_quality(
    page_type: PageType, multiplier: float, cfg: CompressionConfig
) -> int:
    if page_type == PageType.HERO:
        base, floor = cfg.hero_base_quality, cfg.hero_min_quality_v1
    else:
        base, floor = cfg.process_base_quality, cfg.process_min_quality_v1
    return max(min(int(base * multiplier), _CACHE_QUALITY), floor)


def _render_cache(doc: fitz.Document, dpi: int) -> list[bytes]:
    """Render every page once at the given DPI, cached as q95 JPEG bytes."""
    cache: list[bytes] = []
    for page in doc:
        arr = render_page(page, dpi=dpi)
        buf = io.BytesIO()
        Image.fromarray(arr).save(
            buf, format="JPEG", quality=_CACHE_QUALITY, optimize=True
        )
        cache.append(buf.getvalue())
    return cache


def _build(
    doc: fitz.Document,
    pages: list[PageInfo],
    cache: list[bytes],
    multiplier: float,
    cfg: CompressionConfig,
) -> bytes:
    """Assemble a rasterized PDF at the given quality multiplier."""
    out = fitz.open()
    try:
        for info, cached in zip(pages, cache):
            src_page = doc[info.page_num]
            rect = src_page.rect
            quality = _page_quality(info.page_type, multiplier, cfg)
            with Image.open(io.BytesIO(cached)) as img:
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=quality, optimize=True)
            new_page = out.new_page(width=rect.width, height=rect.height)
            new_page.insert_image(new_page.rect, stream=buf.getvalue())
        return out.tobytes(
            garbage=cfg.garbage_level, deflate=cfg.deflate, clean=cfg.clean
        )
    finally:
        out.close()


def compress_v1(
    doc: fitz.Document, pages: list[PageInfo], cfg: CompressionConfig
) -> tuple[bytes, bool]:
    """Run the rasterization path. Returns (pdf_bytes, quality_maxed)."""
    target = cfg.target_bytes
    tolerance = cfg.tolerance_bytes
    dpi = cfg.render_dpi

    while True:
        cache = _render_cache(doc, dpi)

        at_min = _build(doc, pages, cache, config.QUALITY_MULTIPLIER_MIN, cfg)
        if len(at_min) > target:
            new_dpi = max(
                int(dpi * (target / len(at_min)) ** 0.5), config.MIN_RENDER_DPI
            )
            if new_dpi >= dpi:
                raise CompressionError(
                    f"cannot reach {target} bytes even at {dpi} DPI and minimum quality"
                )
            dpi = new_dpi
            continue

        at_max = _build(doc, pages, cache, 1.0, cfg)
        if len(at_max) <= target:
            return at_max, len(at_max) < target - tolerance

        lo, hi = config.QUALITY_MULTIPLIER_MIN, 1.0
        best = at_min
        for _ in range(config.MAX_QUALITY_SEARCH_ITERATIONS):
            mid = (lo + hi) / 2
            data = _build(doc, pages, cache, mid, cfg)
            if len(data) <= target:
                best = data
                lo = mid
            else:
                hi = mid
            if target - tolerance <= len(best) <= target:
                break
        return best, False
