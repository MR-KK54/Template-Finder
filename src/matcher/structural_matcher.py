from typing import List
from rapidfuzz import fuzz, process
from src.models import TableData
from src.utils.logger import get_logger

logger = get_logger("structural_matcher")

class StructuralMatcher:
    """Structural matcher comparing document headings, tables, lists, and page patterns."""

    def compute_heading_similarity(self, headings1: List[str], headings2: List[str]) -> float:
        """Calculates bidirectional match percentage between heading sequences."""
        if not headings1 and not headings2:
            return 100.0
        if not headings1 or not headings2:
            return 0.0

        # 1. Forward match (h1 in h2)
        scores1 = []
        for h1 in headings1:
            best_match = process.extractOne(h1, headings2, scorer=fuzz.token_set_ratio)
            if best_match:
                scores1.append(best_match[1])

        # 2. Reverse match (h2 in h1)
        scores2 = []
        for h2 in headings2:
            best_match = process.extractOne(h2, headings1, scorer=fuzz.token_set_ratio)
            if best_match:
                scores2.append(best_match[1])

        avg1 = (sum(scores1) / len(scores1)) if scores1 else 0.0
        avg2 = (sum(scores2) / len(scores2)) if scores2 else 0.0

        # 3. Sequence alignment
        seq1 = " > ".join(headings1)
        seq2 = " > ".join(headings2)
        seq_score = fuzz.token_sort_ratio(seq1, seq2)

        composite = (avg1 * 0.4) + (avg2 * 0.4) + (seq_score * 0.2)
        return float(min(100.0, max(0.0, composite)))

    def compute_table_similarity(self, tables1: List[TableData], tables2: List[TableData]) -> float:
        """Calculates structural and content similarity between document tables."""
        if not tables1 and not tables2:
            return 100.0
        if not tables1 or not tables2:
            return 0.0

        table_scores = []
        for t1 in tables1:
            best_score = 0.0
            for t2 in tables2:
                # Dimension similarity
                dim_diff = abs(t1.rows - t2.rows) + abs(t1.cols - t2.cols)
                dim_score = max(0.0, 100.0 - (dim_diff * 15.0))

                # Header fuzzy match
                header_str1 = " ".join(t1.headers)
                header_str2 = " ".join(t2.headers)
                header_score = fuzz.token_sort_ratio(header_str1, header_str2) if header_str1 and header_str2 else 50.0

                # Flat content match
                content_score = fuzz.token_set_ratio(t1.flat_text, t2.flat_text) if t1.flat_text and t2.flat_text else 50.0

                composite = (dim_score * 0.3) + (header_score * 0.35) + (content_score * 0.35)
                if composite > best_score:
                    best_score = composite

            table_scores.append(best_score)

        return float(sum(table_scores) / len(table_scores))

    def compute_list_similarity(self, lists1: List[str], lists2: List[str]) -> float:
        """Compares list and bullet item patterns between documents."""
        if not lists1 and not lists2:
            return 100.0
        if not lists1 or not lists2:
            return 0.0

        len_diff = abs(len(lists1) - len(lists2))
        count_score = max(0.0, 100.0 - (len_diff * 10.0))

        content_str1 = " ".join(lists1)
        content_str2 = " ".join(lists2)
        content_score = fuzz.token_set_ratio(content_str1, content_str2)

        return float((count_score * 0.4) + (content_score * 0.6))

    def compute_page_sequence_similarity(self, page_count1: int, page_count2: int) -> float:
        """Calculates page sequence pattern score based on document length ratio and scale invariance."""
        if page_count1 <= 0 or page_count2 <= 0:
            return 0.0
        min_p = min(page_count1, page_count2)
        max_p = max(page_count1, page_count2)
        ratio = (min_p / max_p) * 100.0
        # If both documents have at least 1 page, minimum structural baseline is 60%
        return float(min(100.0, max(60.0, ratio)))

    def compute_header_footer_similarity(self, hf1: List[str], hf2: List[str]) -> float:
        """Calculates header and footer text similarity."""
        if not hf1 and not hf2:
            return 100.0
        if not hf1 or not hf2:
            return 0.0
        s1 = " ".join(hf1)
        s2 = " ".join(hf2)
        return float(fuzz.token_set_ratio(s1, s2))

    def compute_section_sequence_similarity(self, headings1: List[str], headings2: List[str]) -> float:
        """Calculates sequential similarity of document sections and subheadings."""
        if not headings1 and not headings2:
            return 100.0
        if not headings1 or not headings2:
            return 0.0
        seq1 = " > ".join(headings1[:15])
        seq2 = " > ".join(headings2[:15])
        return float(fuzz.token_sort_ratio(seq1, seq2))
