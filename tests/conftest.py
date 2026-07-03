"""Synthetic PDF fixtures for the test suite.

Noise-based JPEGs are used because random noise compresses poorly, which
lets small page counts produce multi-MB files quickly.
"""

import io
from pathlib import Path

import fitz
import numpy as np
import pytest
from PIL import Image

RNG_SEED = 20260703


def noise_jpeg(
    width: int, height: int, quality: int = 95, seed: int = RNG_SEED
) -> bytes:
    """A colorful high-entropy JPEG (compresses poorly, classifies as hero-ish)."""
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 256, size=(height // 8, width // 8, 3), dtype=np.uint8)
    img = Image.fromarray(base).resize((width, height), Image.BILINEAR)
    arr = np.asarray(img).astype(np.int16)
    arr += rng.integers(-40, 40, size=arr.shape, dtype=np.int16)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def rgba_png(width: int, height: int, seed: int = RNG_SEED) -> bytes:
    """A noisy RGBA PNG so PyMuPDF stores it with an SMask."""
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, size=(height, width, 4), dtype=np.uint8)
    arr[..., 3] = np.linspace(0, 255, width, dtype=np.uint8)[None, :]
    buf = io.BytesIO()
    Image.fromarray(arr, mode="RGBA").save(buf, format="PNG")
    return buf.getvalue()


def tiny_png(side: int = 20) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (side, side), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def build_portfolio(
    path: Path,
    n_pages: int = 4,
    image_px: tuple[int, int] = (1400, 1000),
    with_alpha_image: bool = True,
    with_tiny_image: bool = True,
) -> Path:
    """A portfolio-like PDF: vector text + one large photo per page."""
    doc = fitz.open()
    w, h = image_px
    for i in range(n_pages):
        page = doc.new_page(width=595, height=842)  # A4 portrait
        page.insert_text(
            (60, 60), f"Project {i + 1} - Concept Development", fontsize=18
        )
        for line in range(6):
            page.insert_text(
                (60, 90 + line * 16),
                "Design narrative text line describing the process and intent.",
                fontsize=10,
            )
        page.draw_line((60, 200), (535, 200))
        page.insert_image(
            fitz.Rect(60, 220, 535, 560), stream=noise_jpeg(w, h, seed=RNG_SEED + i)
        )
        if with_alpha_image and i == 0:
            page.insert_image(fitz.Rect(60, 580, 300, 750), stream=rgba_png(600, 420))
        if with_tiny_image and i == 0:
            page.insert_image(fitz.Rect(520, 800, 535, 815), stream=tiny_png())
    doc.save(str(path), garbage=4, deflate=True)
    doc.close()
    return path


@pytest.fixture(scope="session")
def portfolio_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A ~4-6 MB synthetic portfolio used by most tests."""
    path = tmp_path_factory.mktemp("fixtures") / "portfolio.pdf"
    return build_portfolio(path)


@pytest.fixture(scope="session")
def small_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A tiny text-only PDF (already under any realistic target)."""
    path = tmp_path_factory.mktemp("fixtures") / "small.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "hello portfolio")
    doc.save(str(path))
    doc.close()
    return path
