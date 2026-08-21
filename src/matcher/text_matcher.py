import re
from typing import Set, List
from rapidfuzz import fuzz, process
from src.utils.logger import get_logger

logger = get_logger("text_matcher")

def normalize_text(text: str) -> str:
    """Normalizes text by removing extra whitespaces, line breaks, and punctuation variations."""
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    text = text.lower().strip()
    return text

class TextMatcher:
    """Fuzzy text matcher utilizing RapidFuzz algorithms with deep content normalization."""

    def compute_text_similarity(self, text1: str, text2: str) -> float:
        """Calculates high-precision fuzzy similarity ratio (0.0 to 100.0) between two text blocks."""
        if not text1 or not text2:
            return 0.0

        n1 = normalize_text(text1)
        n2 = normalize_text(text2)

        if n1 == n2:
            return 100.0

        # Expand character window up to 25,000 characters for deep full-document matching
        t1 = n1[:25000]
        t2 = n2[:25000]

        token_sort = fuzz.token_sort_ratio(t1, t2)
        token_set = fuzz.token_set_ratio(t1, t2)
        partial = fuzz.partial_ratio(t1, t2)

        # High-precision composite score
        score = (token_sort * 0.45) + (token_set * 0.45) + (partial * 0.10)
        return float(min(100.0, max(0.0, score)))

    def compute_paragraph_similarity(self, paras1: List[str], paras2: List[str]) -> float:
        """Calculates match score between two paragraph lists across up to 100 paragraphs."""
        if not paras1 or not paras2:
            return 0.0

        p1_list = [normalize_text(p) for p in paras1 if p and p.strip()][:100]
        p2_list = [normalize_text(p) for p in paras2 if p and p.strip()][:100]

        if not p1_list or not p2_list:
            return 0.0

        matched_scores = []
        for p1 in p1_list:
            if len(p1) < 10:
                continue
            best_match = process.extractOne(p1, p2_list, scorer=fuzz.token_set_ratio)
            if best_match:
                matched_scores.append(best_match[1])

        if not matched_scores:
            return 0.0

        return float(sum(matched_scores) / len(matched_scores))

    def compute_keyword_similarity(self, keywords1: Set[str], keywords2: Set[str]) -> float:
        """Calculates Jaccard similarity index between keyword sets (0.0 to 100.0)."""
        if not keywords1 or not keywords2:
            return 0.0

        intersection = keywords1.intersection(keywords2)
        union = keywords1.union(keywords2)

        if not union:
            return 0.0

        return float((len(intersection) / len(union)) * 100.0)
