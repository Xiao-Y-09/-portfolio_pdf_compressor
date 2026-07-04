"""Top-level orchestration: analysis phase + compression phase.

v4 flow:
1. run_analysis(): thumbnails + AI page classification for the review UI
2. run_compression(): user-confirmed selected_pages drive hero/process
   treatment; fonts are subset before scanning; images are recompressed
   in place (vector text is preserved)

Strategy selection (compression_ratio = target / original):
- ratio > strategy_switch_ratio (0.05) -> v2 vector preserving (default)
- ratio <= 0.05                        -> v1 whole-page rasterization (last resort)
- already under target                 -> passthrough resave

If the v2 path cannot reach the target, the pipeline falls back to v1 on a
freshly opened document.
"""

import base64
import logging
import time
from pathlib import Path

from compressor.classifier import classify_images, classify_pages
from compressor.exceptions import CompressionError
from compressor.pdf_io import (
    generate_thumbnails,
    open_pdf,
    pdf_bytes,
    scan_pdf,
)
from compressor.schemas import (
    AnalysisResult,
    CompressionConfig,
    CompressionResult,
    PageType,
    Strategy,
)
from compressor.strategy_v1 import compress_v1
from compressor.strategy_v2 import compress_v2

logger = logging.getLogger(__name__)


def choose_strategy(original_bytes: int, cfg: CompressionConfig) -> Strategy:
    if original_bytes <= cfg.target_bytes:
        return Strategy.PASSTHROUGH
    ratio = cfg.target_bytes / original_bytes
    if ratio > cfg.strategy_switch_ratio:
        return Strategy.VECTOR_PRESERVING
    return Strategy.PAGE_RASTERIZATION


def run_analysis(input_path: str | Path) -> AnalysisResult:
    """Scan a PDF for the review UI: thumbnails plus per-page AI labels.

    ai_suggested_pages is 1-indexed to match what the user sees.
    """
    input_path = Path(input_path)
    doc = open_pdf(input_path)
    try:
        thumbnails = generate_thumbnails(doc)
        pages = classify_pages(doc)
        page_count = doc.page_count
    finally:
        doc.close()

    classifications = [p.page_type for p in pages]
    return AnalysisResult(
        page_count=page_count,
        original_size_mb=round(input_path.stat().st_size / 1048576, 2),
        thumbnails=[base64.b64encode(t).decode("ascii") for t in thumbnails],
        page_classifications=classifications,
        ai_suggested_pages=[
            p.page_num + 1 for p in pages if p.page_type == PageType.HERO
        ],
    )


def _subset_fonts(doc, cfg: CompressionConfig) -> None:
    """Font subsetting frees image budget; failure must never abort the run."""
    if not cfg.enable_font_subsetting:
        return
    try:
        doc.subset_fonts()
    except Exception as exc:
        logger.warning("font subsetting failed, continuing without it: %s", exc)


def _run_v1(input_path: Path, cfg: CompressionConfig) -> tuple[bytes, bool, int]:
    doc = open_pdf(input_path)
    try:
        pages = classify_pages(doc)
        data, quality_maxed = compress_v1(doc, pages, cfg)
        return data, quality_maxed, doc.page_count
    finally:
        doc.close()


def _run_v2(
    input_path: Path, cfg: CompressionConfig, selected_pages: set[int] | None
) -> tuple[bytes, bool, int]:
    doc = open_pdf(input_path)
    try:
        _subset_fonts(doc, cfg)
        images = scan_pdf(doc)
        if selected_pages is None:
            classify_images(images)
        data, quality_maxed = compress_v2(doc, images, cfg, selected_pages)
        return data, quality_maxed, doc.page_count
    finally:
        doc.close()


def run_compression(
    input_path: str | Path,
    target_size_mb: float,
    selected_pages: list[int] | None = None,
    output_path: str | Path | None = None,
    cfg: CompressionConfig | None = None,
) -> CompressionResult:
    """Compress input_path to at most target_size_mb megabytes.

    selected_pages is the user's 1-indexed list of important pages from the
    review step; None means "use the AI classification".

    Writes the result to output_path (default: alongside the input with a
    ``_compressed`` suffix) and returns a CompressionResult summary.
    """
    started = time.monotonic()
    input_path = Path(input_path)
    if cfg is None:
        cfg = CompressionConfig(target_size_mb=target_size_mb)
    else:
        cfg = cfg.model_copy(update={"target_size_mb": target_size_mb})
    if output_path is None:
        output_path = input_path.with_stem(input_path.stem + "_compressed")
    output_path = Path(output_path)

    selection: set[int] | None = None
    if selected_pages is not None:
        selection = {p - 1 for p in selected_pages if p >= 1}

    original_bytes = input_path.stat().st_size
    strategy = choose_strategy(original_bytes, cfg)

    if strategy == Strategy.PASSTHROUGH:
        doc = open_pdf(input_path)
        try:
            data = pdf_bytes(doc, cfg)
            page_count = doc.page_count
        finally:
            doc.close()
        quality_maxed = True
    elif strategy == Strategy.VECTOR_PRESERVING:
        try:
            data, quality_maxed, page_count = _run_v2(input_path, cfg, selection)
        except CompressionError:
            logger.warning("v2 path failed, falling back to rasterization")
            strategy = Strategy.PAGE_RASTERIZATION
            data, quality_maxed, page_count = _run_v1(input_path, cfg)
    else:
        data, quality_maxed, page_count = _run_v1(input_path, cfg)

    if len(data) > cfg.target_bytes and strategy != Strategy.PASSTHROUGH:
        raise CompressionError(
            f"final size {len(data)} exceeds target {cfg.target_bytes} bytes"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(data)

    return CompressionResult(
        strategy=strategy,
        original_bytes=original_bytes,
        output_bytes=len(data),
        target_bytes=cfg.target_bytes,
        page_count=page_count,
        quality_maxed=quality_maxed,
        duration_seconds=round(time.monotonic() - started, 2),
    )
