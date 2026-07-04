"""Command line interface.

python -m compressor input.pdf --target 15 --output out.pdf
python -m compressor input.pdf --target 10 --selected-pages 1,3,7
"""

import argparse
import sys
from pathlib import Path

from compressor.exceptions import CompressorError
from compressor.pipeline import run_compression


def _parse_pages(raw: str) -> list[int]:
    try:
        pages = sorted({int(p) for p in raw.split(",") if p.strip()})
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "expected comma-separated page numbers, e.g. 1,3,7"
        ) from exc
    if any(p < 1 for p in pages):
        raise argparse.ArgumentTypeError("page numbers are 1-indexed")
    return pages


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compressor",
        description="Compress a portfolio PDF to a hard size target with maximum quality.",
    )
    parser.add_argument("input", type=Path, help="input PDF path")
    parser.add_argument(
        "--target",
        type=float,
        required=True,
        help="target size in MB (e.g. 5, 10, 15, 20)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="output PDF path (default: <input>_compressed.pdf)",
    )
    parser.add_argument(
        "--selected-pages",
        type=_parse_pages,
        default=None,
        metavar="PAGES",
        help="comma-separated 1-indexed pages to treat as important "
        "(default: automatic AI classification)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.input.is_file():
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 2
    if args.target <= 0:
        print("error: --target must be positive", file=sys.stderr)
        return 2

    try:
        result = run_compression(
            args.input, args.target, args.selected_pages, args.output
        )
    except CompressorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out = args.output or args.input.with_stem(args.input.stem + "_compressed")
    print(
        f"strategy={result.strategy.value} "
        f"original={result.original_bytes / 1048576:.1f}MB "
        f"output={result.output_bytes / 1048576:.2f}MB "
        f"target={result.target_bytes / 1048576:.1f}MB "
        f"pages={result.page_count} "
        f"time={result.duration_seconds:.1f}s"
    )
    if result.quality_maxed:
        print("note: output is below target because quality reached its ceiling")
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
