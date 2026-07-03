"""Top-level orchestration: pick a strategy from the compression ratio and run it.

compression_ratio = target_size / original_size
- ratio > strategy_switch_ratio  -> v2 (vector preserving)
- ratio <= strategy_switch_ratio -> v1 (whole-page rasterization)
- already under target           -> passthrough resave

If the v2 path cannot reach the target (physical overhead limit, pitfall 6),
the pipeline falls back to v1 on a freshly opened document.
"""

import time
from pathlib import Path

from compressor.classifier import classify_images, classify_pages
from compressor.exceptions import CompressionError
from compressor.pdf_io import open_pdf, pdf_bytes, scan_pdf
from compressor.schemas import CompressionConfig, CompressionResult, Strategy
from compressor.strategy_v1 import compress_v1
from compressor.strategy_v2 import compress_v2


def choose_strategy(original_bytes: int, cfg: CompressionConfig) -> Strategy:
    if original_bytes <= cfg.target_bytes:
        return Strategy.PASSTHROUGH
    ratio = cfg.target_bytes / original_bytes
    if ratio > cfg.strategy_switch_ratio:
        return Strategy.VECTOR_PRESERVING
    return Strategy.PAGE_RASTERIZATION


def _run_v1(input_path: Path, cfg: CompressionConfig) -> tuple[bytes, bool, int]:
    doc = open_pdf(input_path)
    try:
        pages = classify_pages(doc)
        data, quality_maxed = compress_v1(doc, pages, cfg)
        return data, quality_maxed, doc.page_count
    finally:
        doc.close()


def _run_v2(input_path: Path, cfg: CompressionConfig) -> tuple[bytes, bool, int]:
    doc = open_pdf(input_path)
    try:
        images = scan_pdf(doc)
        classify_images(images)
        data, quality_maxed = compress_v2(doc, images, cfg)
        return data, quality_maxed, doc.page_count
    finally:
        doc.close()


def compress_pdf(
    input_path: str | Path,
    target_size_mb: float,
    output_path: str | Path | None = None,
    cfg: CompressionConfig | None = None,
) -> CompressionResult:
    """Compress input_path to at most target_size_mb megabytes.

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
            data, quality_maxed, page_count = _run_v2(input_path, cfg)
        except CompressionError:
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
