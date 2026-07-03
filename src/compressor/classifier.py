"""Hero/process classification via OpenCV heuristics.

Two interfaces:
- classify_images(): image-level labels for the v2 (vector-preserving) path
- classify_pages(): page-level labels for the v1 (rasterization) path

Heuristics only — no vision models. Hero means "photo/render the applicant
cares about"; process means "line art, diagrams, decorative content".
"""

import cv2
import fitz
import numpy as np

from compressor import config
from compressor.exceptions import ClassificationError
from compressor.pdf_io import decode_image, render_page
from compressor.schemas import ImageInfo, PageInfo, PageType


def colorfulness(arr: np.ndarray) -> float:
    """Hasler-Suesstrunk colorfulness metric on an RGB array."""
    r, g, b = (
        arr[..., 0].astype(np.float32),
        arr[..., 1].astype(np.float32),
        arr[..., 2].astype(np.float32),
    )
    rg = r - g
    yb = 0.5 * (r + g) - b
    std = np.sqrt(np.std(rg) ** 2 + np.std(yb) ** 2)
    mean = np.sqrt(np.mean(rg) ** 2 + np.mean(yb) ** 2)
    return float(std + 0.3 * mean)


def _white_ratio(arr: np.ndarray) -> float:
    return float(np.mean(np.all(arr > 240, axis=-1)))


def _edge_density(arr: np.ndarray) -> float:
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 100, 200)
    return float(np.count_nonzero(edges)) / edges.size


def classify_image_array(
    arr: np.ndarray, display_ratio: float
) -> tuple[PageType, float]:
    """Classify one decoded image given its on-page display ratio."""
    color = colorfulness(arr)
    white = _white_ratio(arr)
    edges = _edge_density(arr)

    is_line_art = (
        white >= config.WHITE_RATIO_LINEART_THRESHOLD
        and edges >= config.EDGE_DENSITY_LINEART_THRESHOLD
        and color < config.COLORFULNESS_HERO_THRESHOLD
    )
    if is_line_art:
        return PageType.PROCESS, 0.9

    color_score = min(color / (2 * config.COLORFULNESS_HERO_THRESHOLD), 1.0)
    display_score = min(display_ratio / config.DISPLAY_RATIO_HERO_THRESHOLD, 1.0)
    hero_score = 0.45 * color_score + 0.35 * display_score + 0.20 * (1.0 - white)

    if hero_score >= 0.5:
        return PageType.HERO, min(0.5 + hero_score / 2, 0.95)
    return PageType.PROCESS, min(0.5 + (0.5 - hero_score), 0.95)


def classify_images(images: list[ImageInfo]) -> None:
    """Label every ImageInfo in place (classification + confidence)."""
    for info in images:
        try:
            arr = decode_image(info, max_dim=config.CLASSIFY_MAX_DIM)
            info.classification, info.confidence = classify_image_array(
                arr, info.display_ratio
            )
        except Exception as exc:
            raise ClassificationError(
                f"failed to classify image xref={info.xref} on page {info.page_num}: {exc}"
            ) from exc


def classify_page_array(arr: np.ndarray) -> tuple[PageType, float]:
    """Classify one rendered page: image-dominant (hero) vs text/diagram (process)."""
    ink_ratio = 1.0 - _white_ratio(arr)
    color = colorfulness(arr)

    ink_score = min(ink_ratio / config.PAGE_INK_RATIO_HERO_THRESHOLD, 1.0)
    color_score = min(color / (2 * config.PAGE_COLORFULNESS_HERO_THRESHOLD), 1.0)
    hero_score = 0.6 * ink_score + 0.4 * color_score

    if hero_score >= 0.6:
        return PageType.HERO, min(0.5 + hero_score / 2, 0.95)
    return PageType.PROCESS, min(0.5 + (0.6 - hero_score), 0.95)


def classify_pages(doc: fitz.Document) -> list[PageInfo]:
    """Render each page at a small DPI and label it."""
    pages: list[PageInfo] = []
    for page in doc:
        try:
            arr = render_page(page, dpi=config.PAGE_CLASSIFY_DPI)
            page_type, confidence = classify_page_array(arr)
        except Exception as exc:
            raise ClassificationError(
                f"failed to classify page {page.number}: {exc}"
            ) from exc
        pages.append(
            PageInfo(page_num=page.number, page_type=page_type, confidence=confidence)
        )
    return pages
