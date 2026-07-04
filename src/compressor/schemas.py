"""Pydantic data models shared across the compressor package."""

from enum import Enum

import numpy as np
from pydantic import BaseModel, ConfigDict, Field


class PageType(str, Enum):
    """Classification label for a page (v1 path) or an image (v2 path)."""

    HERO = "hero"
    PROCESS = "process"


class Strategy(str, Enum):
    """Which compression path was selected."""

    VECTOR_PRESERVING = "vector_preserving"  # v2: compress embedded images only
    PAGE_RASTERIZATION = "page_rasterization"  # v1: rasterize whole pages
    PASSTHROUGH = "passthrough"  # already under target, just resave


class ImageInfo(BaseModel):
    """Metadata for one embedded image object (v2 path)."""

    xref: int
    page_num: int
    original_bytes: int
    original_data: bytes = Field(default=b"", exclude=True)
    original_ext: str = "jpeg"
    original_smask_data: bytes = Field(default=b"", exclude=True)
    smask_xref: int = 0
    pixel_width: int
    pixel_height: int
    format: str
    display_rect: tuple[float, float, float, float]
    display_ratio: float  # displayed area / page area, in [0, 1]
    effective_ppi: float
    classification: PageType = PageType.PROCESS
    confidence: float = 0.5


class PageInfo(BaseModel):
    """Metadata for one page (v1 path)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    page_num: int
    page_type: PageType
    confidence: float
    image_array: np.ndarray | None = Field(default=None, exclude=True)


class CompressionConfig(BaseModel):
    """All tunable knobs. Defaults live here; scan-time constants live in config.py."""

    target_size_mb: float
    tolerance_mb: float = 0.3

    # strategy switch (v4: rasterization is a last resort only)
    strategy_switch_ratio: float = 0.05  # compression_ratio <= 0.05 -> v1 path

    # v2 path (per-image PPI + quality)
    hero_max_ppi: int = 150
    hero_min_ppi: int = 120
    process_max_ppi: int = 96
    process_min_ppi: int = 72
    hero_max_quality: int = 95
    process_max_quality: int = 75
    hero_min_quality: int = 45
    process_min_quality: int = 20
    small_image_quality_floor: int = 20

    # v4: format selection and grayscale detection
    jpeg2000_quality_threshold: int = 40  # quality below this -> JPEG 2000
    enable_font_subsetting: bool = True
    enable_grayscale_detection: bool = True
    grayscale_channel_diff_threshold: int = 5  # max RGB channel spread to call it gray

    # v1 path (whole-page rasterization)
    render_dpi: int = 200
    hero_base_quality: int = 90
    process_base_quality: int = 55
    hero_min_quality_v1: int = 50
    process_min_quality_v1: int = 20

    # weights (shared by both paths)
    hero_label_weight: float = 1.0
    process_label_weight: float = 0.4
    large_size_weight: float = 1.0
    medium_size_weight: float = 0.6
    small_size_weight: float = 0.3

    # save options
    garbage_level: int = 4
    deflate: bool = True
    clean: bool = True

    # search limits
    max_iterations_per_image: int = 8
    max_global_adjust_rounds: int = 5

    @property
    def target_bytes(self) -> int:
        return int(self.target_size_mb * 1024 * 1024)

    @property
    def tolerance_bytes(self) -> int:
        return int(self.tolerance_mb * 1024 * 1024)


class CompressionResult(BaseModel):
    """Summary of one compression run."""

    strategy: Strategy
    original_bytes: int
    output_bytes: int
    target_bytes: int
    page_count: int
    quality_maxed: bool = (
        False  # output is below the window because quality hit its ceiling
    )
    duration_seconds: float = 0.0


class AnalysisResult(BaseModel):
    """Output of the analysis phase, shown to the user for page review.

    Page numbers in ai_suggested_pages are 1-indexed, matching what the
    user sees in the review UI.
    """

    job_id: str = ""
    page_count: int
    original_size_mb: float
    thumbnails: list[str]  # base64-encoded JPEG, one per page
    page_classifications: list[PageType]
    ai_suggested_pages: list[int]


class CompressionRequest(BaseModel):
    """User confirmation payload: target size plus reviewed page selection."""

    target_size_mb: float
    selected_pages: list[int]  # 1-indexed pages the user marked as important
