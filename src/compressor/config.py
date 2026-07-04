"""Module-level constants: scan filters, classifier thresholds, size buckets.

Per-run tunables live in schemas.CompressionConfig; everything here is a
process-wide constant that code must not hardcode inline.
"""

MB = 1024 * 1024

# --- scan filters (pitfall 7: skip tiny decorative images) ---
MIN_IMAGE_PIXEL_AREA = 4096  # width * height below this -> skip
MIN_IMAGE_BYTES = 5120  # stream size below this -> skip

# --- classifier: image level ---
# Colorfulness (Hasler-Suesstrunk) above this suggests a photo/render.
COLORFULNESS_HERO_THRESHOLD = 18.0
# Fraction of near-white pixels above this suggests line art / diagram.
WHITE_RATIO_LINEART_THRESHOLD = 0.75
# Edge density (Canny) above this with low colorfulness suggests line art.
EDGE_DENSITY_LINEART_THRESHOLD = 0.08
# Images covering at least this fraction of the page lean hero.
DISPLAY_RATIO_HERO_THRESHOLD = 0.30
# Cap for the decoded array's long side during classification (speed).
CLASSIFY_MAX_DIM = 512

# --- classifier: page level ---
# Non-white page coverage above this suggests an image-dominant (hero) page.
PAGE_INK_RATIO_HERO_THRESHOLD = 0.55
PAGE_COLORFULNESS_HERO_THRESHOLD = 12.0
# DPI used when rendering pages purely for classification.
PAGE_CLASSIFY_DPI = 48

# --- v2 budget allocation: display-area buckets ---
LARGE_DISPLAY_RATIO = 0.5  # image covers >= 50% of page area
MEDIUM_DISPLAY_RATIO = 0.15

# --- v4: thumbnails for the review UI ---
THUMBNAIL_DPI = 40
THUMBNAIL_JPEG_QUALITY = 70

# --- v4: JPEG quality -> JPEG 2000 compression rate mapping (pitfall 8) ---
# JPEG 2000 takes a compression rate (original/compressed), not a quality.
# Anchored so the boundary is roughly continuous: JPEG q40 compresses photos
# at ~30:1, and each quality step below the threshold adds RATE_SLOPE.
J2K_RATE_AT_THRESHOLD = 30.0
J2K_RATE_SLOPE = 2.0

# --- v1 rasterization ---
MIN_RENDER_DPI = 72  # never rasterize below this
QUALITY_MULTIPLIER_MIN = 0.15  # lower bound for the global quality multiplier search
MAX_QUALITY_SEARCH_ITERATIONS = 8

# --- server layer ---
MAX_UPLOAD_MB = 200
ALLOWED_TARGETS_MB = (5.0, 10.0, 15.0, 20.0)
RATE_LIMIT_MAX_REQUESTS = 10  # per window per IP
RATE_LIMIT_WINDOW_SECONDS = 3600
JOB_RETENTION_SECONDS = 3600
