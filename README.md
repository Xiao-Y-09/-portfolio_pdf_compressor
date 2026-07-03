# Portfolio Compressor

Smart PDF compressor for art/design portfolios. Upload a 60-100 MB portfolio,
pick a hard size limit (5/10/15/20 MB), get the best possible visual quality
under that limit.

## How it works

The tool picks a strategy automatically from `compression_ratio = target / original`:

- **ratio > 0.4 — vector preserving (v2)**: text and line art stay vector;
  only embedded images are recompressed. Each image gets a byte budget based
  on hero/process classification and on-page display size, then is fit to the
  budget by capping PPI and binary-searching JPEG quality.
- **ratio <= 0.4 — page rasterization (v1)**: every page is rendered to a
  JPEG. Hero pages get higher quality than process pages; a global quality
  multiplier is binary-searched to land just under the target.

Classification is OpenCV heuristics (colorfulness, white ratio, edge density,
display coverage) — no ML models, no external binaries, pure PyMuPDF + Pillow.

## CLI

```bash
python -m compressor input.pdf --target 15 --output out.pdf
```

## API server

```bash
python -m uvicorn server.main:app --port 8000
```

- `POST /api/jobs` — multipart upload (`file`, `target_mb` in {5, 10, 15, 20}) → `{job_id}`
- `GET /api/jobs/{job_id}` — status + result summary
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
