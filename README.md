# Portfolio Compressor

Smart PDF compressor for art/design portfolios. Upload a 60-100 MB portfolio,
pick a hard size limit (5/10/15/20 MB), get the best possible visual quality
under that limit.

## How it works (v4)

**Vector text is non-negotiable.** The default path keeps all text and line
art as vectors and only recompresses embedded images:

1. **Analyze**: every page gets a thumbnail and an AI hero/process label
   (OpenCV heuristics — colorfulness, white ratio, edge density, coverage).
2. **Review**: the user confirms or adjusts which pages are "important".
3. **Compress**: fonts are subset (`doc.subset_fonts()`), then each image is
   fit to a byte budget derived from its page's label and display size —
   PPI capping first (hero ≤150, process ≤96), then a quality binary search.
   Near-grayscale images are stored single-channel; quality below 40 switches
   from JPEG to JPEG 2000 to avoid block artifacts.

Whole-page rasterization survives only as a last resort for extreme ratios
(`target/original <= 0.05`) or when the vector path physically cannot reach
the target. Pure PyMuPDF + Pillow + OpenCV — no ML models, no external binaries.

## CLI

```bash
python -m compressor input.pdf --target 15 --output out.pdf
python -m compressor input.pdf --target 10 --selected-pages 1,3,7
```

## API server

```bash
python -m uvicorn server.main:app --port 8000
```

- `POST /api/jobs` — multipart upload (`file`) → analysis: thumbnails,
  per-page classifications, AI-suggested important pages
- `POST /api/jobs/{job_id}/confirm` — `{target_size_mb, selected_pages}`
  (target in {5, 10, 15, 20}, pages 1-indexed) starts compression
- `GET /api/jobs/{job_id}` — status (`waiting_confirm/processing/done/error`) + result
- `GET /api/jobs/{job_id}/download` — the compressed PDF

Jobs live in memory, expire after an hour, and are rate limited per IP.

## Web frontend

```bash
cd web && npm run dev
```

Next.js app on http://localhost:3000 (expects the API on port 8000,
override with `NEXT_PUBLIC_API_URL`).

## Development

```bash
python -m venv .venv
.venv/Scripts/pip install -e .[dev]
.venv/Scripts/python -m pytest
```

Project layout and design decisions: see `PLANNING.md`; progress log: `PROGRESS.md`.
