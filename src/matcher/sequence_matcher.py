import difflib
from typing import List, Tuple, Callable
from rapidfuzz import fuzz
from src.matcher.text_matcher import normalize_text
from src.models import TableData
from src.utils.logger import get_logger

logger = get_logger("sequence_matcher")


def full_text_order_ratio(pdf_text: str, word_text: str, max_chars: int = 60000) -> float:
    """Ordered containment ratio of pdf_text within word_text (0.0 to 100.0).

    Uses difflib.SequenceMatcher relative to min(len(pdf_text), len(word_text))
    so partial exports or bundled documents receive fair sequence scores."""
    if not pdf_text or not word_text:
        return 0.0 if (pdf_text or word_text) else 100.0
    a = normalize_text(pdf_text)[:max_chars]
    b = normalize_text(word_text)[:max_chars]
    if not a or not b:
        return 0.0
    if a == b:
        return 100.0
    sm = difflib.SequenceMatcher(None, a, b, autojunk=True)
    matched = sum(blk.size for blk in sm.get_matching_blocks())
    denom = min(len(a), len(b))
    return float((matched / denom) * 100.0) if denom > 0 else 0.0


def ordered_coverage(pdf_text: str, word_text: str, max_chars: int = 60000) -> float:
    """Bi-directional source-verification coverage (0.0 to 100.0).

    Calculates max(pdf_coverage, word_coverage) so that if either:
    1) the PDF is an export/section of the Word document, OR
    2) the Word template is contained within a multi-page PDF submission,
    the match is correctly detected at ~100% coverage."""
    if not pdf_text or not word_text:
        return 0.0
    a = normalize_text(pdf_text)[:max_chars]
    b = normalize_text(word_text)[:max_chars]
    if not a or not b:
        return 0.0
    if a == b:
        return 100.0
    sm = difflib.SequenceMatcher(None, a, b, autojunk=True)
    matched = sum(blk.size for blk in sm.get_matching_blocks())
    pdf_cov = (matched / len(a)) * 100.0
    word_cov = (matched / len(b)) * 100.0
    return float(max(pdf_cov, word_cov))


def ordered_list_ratio(
    items_a: List[str],
    items_b: List[str],
    scorer: Callable = fuzz.token_set_ratio,
    min_score: float = 65.0
) -> Tuple[float, int]:
    """For each item of items_a (in document order), finds the best matching
    item in the remaining suffix of items_b. Items must be found in order.
    Evaluated relative to min(len(items_a), len(items_b)) so partial documents
    are not penalized. Returns (matched_ratio 0-100, matched_count)."""
    if not items_a and not items_b:
        return 100.0, 0
    if not items_a or not items_b:
        return 0.0, 0

    items_b = [str(x) for x in items_b]
    matched = 0
    pos = 0
    for item in items_a:
        best_idx = -1
        best_score = 0.0
        for i in range(pos, len(items_b)):
            score = float(scorer(str(item), items_b[i]))
            if score > best_score:
                best_score = score
                best_idx = i
        if best_idx >= 0 and best_score >= min_score:
            matched += 1
            pos = best_idx + 1

    denom = min(len(items_a), len(items_b))
    ratio = (matched / denom) * 100.0 if denom > 0 else 0.0
    return float(ratio), matched


def table_sequence_ratio(tables_a: List[TableData], tables_b: List[TableData]) -> float:
    """Compares tables positionally (table i vs table i) to verify that the
    table sequence of the PDF matches the Word document in order. Returns
    (0.0 to 100.0)."""
    if not tables_a and not tables_b:
        return 100.0
    if not tables_a or not tables_b:
        return 0.0

    positional = []
    n = min(len(tables_a), len(tables_b))
    for i in range(n):
        t1, t2 = tables_a[i], tables_b[i]
        dim_diff = abs(t1.rows - t2.rows) + abs(t1.cols - t2.cols)
        dim_score = max(0.0, 100.0 - (dim_diff * 15.0))

        header_str1 = " ".join(t1.headers)
        header_str2 = " ".join(t2.headers)
        if header_str1 and header_str2:
            header_score = float(fuzz.token_sort_ratio(header_str1, header_str2))
        else:
            header_score = 100.0 if (not header_str1 and not header_str2) else 50.0

        if t1.flat_text and t2.flat_text:
            content_score = float(fuzz.token_set_ratio(t1.flat_text, t2.flat_text))
        else:
            content_score = 100.0 if (not t1.flat_text and not t2.flat_text) else 50.0

        positional.append((dim_score * 0.3) + (header_score * 0.35) + (content_score * 0.35))

    count_sim = (min(len(tables_a), len(tables_b)) / max(len(tables_a), len(tables_b))) * 100.0
    avg_positional = (sum(positional) / len(positional)) if positional else 0.0
    return float((avg_positional * 0.7) + (count_sim * 0.3))


def header_footer_ratio(hf_a: List[str], hf_b: List[str]) -> float:
    """Jaccard-style similarity between header/footer text sets (0.0 to 100.0)."""
    if not hf_a and not hf_b:
        return 100.0
    if not hf_a or not hf_b:
        return 0.0
    set_a = {normalize_text(h) for h in hf_a if h and h.strip()}
    set_b = {normalize_text(h) for h in hf_b if h and h.strip()}
    if not set_a or not set_b:
        return 0.0
    union = set_a | set_b
    return float((len(set_a & set_b) / len(union)) * 100.0)


def count_ratio(count_a: int, count_b: int) -> float:
    """Similarity of two counts based on min/max ratio (0.0 to 100.0)."""
    if count_a <= 0 or count_b <= 0:
        return 0.0 if (count_a != count_b) else 100.0
    return (min(count_a, count_b) / max(count_a, count_b)) * 100.0