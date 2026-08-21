import hashlib
from typing import List
from src.matcher.text_matcher import normalize_text
from src.models import DocumentFeatures, TableData


def build_fingerprint(doc: DocumentFeatures) -> str:
    """Builds a compact deterministic fingerprint string from the full document
    feature set (Stage 1). Identical documents produce identical fingerprints."""
    parts = [
        normalize_text(doc.full_text),
        "H:" + "|".join(normalize_text(h) for h in doc.headings),
        "P:" + "|".join(normalize_text(p) for p in doc.paragraphs),
        "L:" + "|".join(normalize_text(l) for l in doc.lists),
        "HF:" + "|".join(normalize_text(h) for h in doc.headers_footers),
        "T:" + "|".join(normalize_text(t.flat_text) for t in doc.tables),
        f"PAGES:{doc.page_count}",
        f"SECTIONS:{doc.section_count}",
    ]
    payload = "\n".join(parts)
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def tables_fingerprint_part(tables: List[TableData]) -> str:
    return "|".join(normalize_text(t.flat_text) for t in tables)