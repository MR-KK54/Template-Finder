import os
from pathlib import Path

# Base Paths
APP_DATA_DIR = Path.home() / ".pdf_template_finder"
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = os.environ.get("PDF_FINDER_DB", str(APP_DATA_DIR / "index_cache.db"))

# Matching Configuration Weights (Sums to 1.0)
DEFAULT_WEIGHTS = {
    "text": 0.20,             # Full content RapidFuzz / Token matching
    "semantic": 0.20,         # SentenceTransformer vector similarity
    "headings": 0.15,         # Heading & subheading hierarchy match
    "paragraphs": 0.10,       # Paragraph content & sequence match
    "tables": 0.10,           # Table rows, cols, headers & cell content
    "keywords": 0.05,         # Key phrase & entity overlap match
    "structure": 0.05,        # List, bullets & numbering pattern match
    "section": 0.05,          # Section sequence pattern match
    "page_sequence": 0.05,    # Page sequence & length match
    "headers_footers": 0.05   # Headers & footers text match
}

# Search Filters & Thresholds
DEFAULT_SIMILARITY_THRESHOLD = 100.0  # Default minimum match percentage (only exact original source matches)
SUPPORTED_WORD_EXTENSIONS = {".docx", ".doc"}
SUPPORTED_PDF_EXTENSIONS = {".pdf"}

# OCR & Feature Limits
MAX_SAMPLES_SEMANTIC = 1000  # Truncate ultra-large text blocks for fast embedding
SCANNED_PDF_IMAGE_COVERAGE_RATIO = 0.8  # Threshold for scanned page detection
SCANNED_PDF_MAX_CHAR_COUNT = 50        # Max raw characters to consider a page non-scanned

# Index schema/feature version: bump to force a one-time full re-index
# when extraction features change (e.g. page-count estimation, header ordering).
INDEX_VERSION = 6
