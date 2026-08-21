from typing import Callable, Dict, List, Tuple, Optional, Union
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime

from rapidfuzz import fuzz

from src.models import DocumentFeatures, MatchResult, StageReport
from src.matcher.text_matcher import TextMatcher, normalize_text
from src.matcher.semantic_matcher import SemanticMatcher
from src.matcher.sequence_matcher import (
    full_text_order_ratio,
    ordered_coverage,
    ordered_list_ratio,
    table_sequence_ratio,
    header_footer_ratio,
    count_ratio,
)
from src.utils.file_utils import format_file_size
from src.utils.logger import get_logger

logger = get_logger("hybrid_comparator")

# ---------------------------------------------------------------------------
# Pipeline thresholds (do not tune weights here - these are reject/validation
# gates, not similarity weights)
# ---------------------------------------------------------------------------
CONTENT_REJECT_MIN = 35.0      # Stage 3: below this the candidate is rejected
TEXT_SEQ_REJECT_MIN = 15.0     # Stage 3: ordered full-text ratio floor
STRUCTURE_GATE = 50.0          # Stage 5: structure below this caps semantic influence
STRUCTURE_CAP = 60.0           # max overall score when structure is weak
CONTENT_CAP = 70.0             # max overall score when content is weak
VALIDATION_TEXT_SEQ_MIN = 25.0
VALIDATION_TABLE_MIN = 30.0
VALIDATION_HEADING_MIN = 40.0
VALIDATION_PAGE_MIN = 10.0
VALIDATION_HF_MIN = 40.0

# Source verification gates (Stage 6): a candidate whose PDF content is almost
# fully contained in order, with a plausible page-count relationship, is the
# verified original source of the PDF - the "perfect" document.
SOURCE_COVERAGE_MIN = 85.0
SOURCE_PAGE_SIM_MIN = 40.0
SOURCE_MIN_PDF_CHARS = 50

CONTENT_W = {"text": 0.35, "paragraphs": 0.25, "headings": 0.20, "tables": 0.10, "lists": 0.05, "headers_footers": 0.05, "front_page": 0.15}


class HybridComparator:
    """Multi-stage AI document retrieval engine.

    Stage 1: Indexing (src/indexer) - fingerprints stored in the index DB.
    Stage 2: Candidate retrieval - Top-20 candidates from the fingerprint index.
    Stage 3: Exact content verification - ordered paragraph/heading/table/list
             sequence matching. Candidates failing sequence checks are rejected.
    Stage 4: Structural verification - page/section/table/heading counts; large
             structural differences reduce the confidence score.
    Stage 5: Semantic verification - semantic similarity, gated by structure.
    Stage 6: Final validation - all-or-nothing verification before ranking.
    """

    def __init__(
        self,
        semantic_matcher: Optional[SemanticMatcher] = None
    ):
        self.text_matcher = TextMatcher()
        self.semantic_matcher = semantic_matcher or SemanticMatcher()

    # ------------------------------------------------------------------
    # Stage 2 - Candidate Retrieval
    # ------------------------------------------------------------------
    def retrieve_candidates(
        self,
        pdf_doc: DocumentFeatures,
        word_docs: List[DocumentFeatures],
        top_k: int = 20,
        return_scores: bool = False
    ) -> Union[List[DocumentFeatures], Tuple[List[DocumentFeatures], List[float]]]:
        """Ranks all indexed fingerprints with cheap retrieval scores
        (semantic + token overlap + keyword Jaccard) and returns only the
        Top-k candidates for the expensive deep comparison stages. With
        return_scores=True also returns the semantic score per candidate
        so the deep stages can reuse them (no second corpus encode)."""
        if not word_docs:
            return ([], []) if return_scores else []

        candidate_texts = [doc.full_text for doc in word_docs]

        # Prefer cached index-time embeddings (faster retrieval); fall back to
        # query-time batch encoding for documents indexed before this feature.
        cached_embs = []
        all_cached = True
        for doc in word_docs:
            if doc.embedding_json:
                try:
                    cached_embs.append([float(x) for x in doc.embedding_json])
                except Exception:
                    all_cached = False
                    break
            else:
                all_cached = False
                break

        if all_cached and cached_embs:
            pdf_emb = self.semantic_matcher.compute_embedding(pdf_doc.full_text)
            semantic_scores = self.semantic_matcher.cosine_from_embeddings(pdf_emb, cached_embs) \
                if pdf_emb else [0.0] * len(word_docs)
        else:
            semantic_scores = self.semantic_matcher.compute_semantic_similarity_batch(
                pdf_doc.full_text, candidate_texts
            )

        scored: List[Tuple[float, int]] = []
        pdf_front_text = ""
        if pdf_doc.pages and pdf_doc.pages[0].text.strip():
            pdf_front_text = pdf_doc.pages[0].text
        else:
            pdf_front_text = pdf_doc.full_text

        import re
        pdf_ref_codes = set(re.findall(r'\b[A-Z0-9]{2,10}(?:-[A-Z0-9]{2,10})+\b', pdf_doc.full_text.upper()))
        pdf_ref_codes.update(re.findall(r'\b[A-Z]\d{7,10}\b', pdf_doc.full_text.upper()))
        pdf_ref_codes = {c for c in pdf_ref_codes if len(c) >= 5}

        for idx, doc in enumerate(word_docs):
            doc_all = (doc.filename + " " + doc.full_text).upper()
            ref_matches = [c for c in pdf_ref_codes if c in doc_all]
            ref_boost = min(40.0, len(ref_matches) * 20.0)

            text_overlap = 0.0
            if pdf_doc.full_text and doc.full_text:
                text_overlap = fuzz.token_set_ratio(
                    pdf_doc.full_text[:8000], doc.full_text[:8000]
                )

            front_overlap = 0.0
            if pdf_front_text and doc.full_text:
                front_overlap = fuzz.token_set_ratio(
                    pdf_front_text[:8000], doc.full_text[:8000]
                )

            keyword_score = 0.0
            if pdf_doc.keywords and doc.keywords:
                union = pdf_doc.keywords | doc.keywords
                if union:
                    keyword_score = (len(pdf_doc.keywords & doc.keywords) / len(union)) * 100.0

            w_ratio = fuzz.WRatio(pdf_doc.full_text[:5000], doc.full_text[:5000]) if (pdf_doc.full_text and doc.full_text) else 0.0

            retrieval_score = (semantic_scores[idx] * 0.3) + (front_overlap * 0.25) + (text_overlap * 0.2) + (w_ratio * 0.15) + (keyword_score * 0.1) + ref_boost
            scored.append((retrieval_score, idx))

        scored.sort(key=lambda item: item[0], reverse=True)
        selected = scored if top_k is None else scored[:max(1, top_k)]
        top_indices = [idx for _, idx in selected]
        logger.info(f"Stage 2 Retrieval: selected Top {len(top_indices)} candidates from {len(word_docs)} indexed documents.")
        selected_docs = [word_docs[idx] for idx in top_indices]
        if return_scores:
            selected_scores = [semantic_scores[idx] for idx in top_indices]
            return selected_docs, selected_scores
        return selected_docs

    # ------------------------------------------------------------------
    # Stages 3-6 - Deep comparison of a single candidate
    # ------------------------------------------------------------------
    def compare(
        self,
        pdf_doc: DocumentFeatures,
        word_doc: DocumentFeatures,
        precomputed_semantic_score: Optional[float] = None
    ) -> MatchResult:
        """Runs the deep comparison pipeline (stages 3-6) against one candidate
        and returns a MatchResult with full stage reports and rejection reason."""
        stage_reports: List[StageReport] = []
        rejected = False
        rejected_reason = ""

        # --- ordered sequence components -----------------------------------
        text_coverage = ordered_coverage(pdf_doc.full_text, word_doc.full_text)
        text_ratio = full_text_order_ratio(pdf_doc.full_text, word_doc.full_text)
        text_seq = (text_coverage * 0.6) + (text_ratio * 0.4)

        # Front-page-first matching: the first page of the PDF (title/cover
        # page) is the most stable identity signal. Later pages may differ
        # (translations, DTP rendering, annexes), but the front page of the
        # source PDF must be contained in the original Word document.
        pdf_front_text = ""
        if pdf_doc.pages and pdf_doc.pages[0].text.strip():
            pdf_front_text = pdf_doc.pages[0].text
        else:
            pdf_front_text = pdf_doc.full_text
        front_coverage = ordered_coverage(pdf_front_text, word_doc.full_text)
        front_ratio = full_text_order_ratio(pdf_front_text, word_doc.full_text)
        front_seq = (front_coverage * 0.6) + (front_ratio * 0.4)

        # Protocol ID / Reference Code Overlap Check
        import re
        pdf_ref_codes = set(re.findall(r'\b[A-Z0-9]{2,10}(?:-[A-Z0-9]{2,10})+\b', pdf_doc.full_text.upper()))
        pdf_ref_codes.update(re.findall(r'\b[A-Z]\d{7,10}\b', pdf_doc.full_text.upper()))
        pdf_ref_codes = {c for c in pdf_ref_codes if len(c) >= 5}

        doc_all = (word_doc.filename + " " + word_doc.full_text).upper()
        matched_ref_codes = [c for c in pdf_ref_codes if c in doc_all]
        ref_boost = min(40.0, len(matched_ref_codes) * 20.0) if matched_ref_codes else 0.0

        # Multi-page structural page alignment: find best matching page in PDF
        best_page_cov = 0.0
        if pdf_doc.pages:
            for page_item in pdf_doc.pages[:10]:
                if page_item.text and page_item.text.strip():
                    cov = ordered_coverage(page_item.text, word_doc.full_text)
                    if cov > best_page_cov:
                        best_page_cov = cov

        # A candidate whose front page, best page, or reference protocol code matches is never rejected
        effective_text_seq = max(text_seq, front_seq, best_page_cov)
        if matched_ref_codes:
            effective_text_seq = max(effective_text_seq, 65.0 + ref_boost)

        para_seq, para_matched = ordered_list_ratio(
            pdf_doc.paragraphs[:150], word_doc.paragraphs[:300], min_score=60.0
        )
        head_seq, head_matched = ordered_list_ratio(
            pdf_doc.headings[:50], word_doc.headings[:100], min_score=80.0
        )
        list_seq, list_matched = ordered_list_ratio(
            pdf_doc.lists[:100], word_doc.lists[:200], min_score=60.0
        )
        table_seq = table_sequence_ratio(pdf_doc.tables, word_doc.tables)
        hf_score = header_footer_ratio(pdf_doc.headers_footers, word_doc.headers_footers)
        keyword_score = self._keyword_jaccard(pdf_doc.keywords, word_doc.keywords)

        # --- Stage 3: Exact Content Verification ---------------------------
        applicable: List[Tuple[str, float]] = [("text", effective_text_seq), ("front_page", front_seq)]
        if pdf_doc.paragraphs:
            applicable.append(("paragraphs", para_seq))
        if pdf_doc.headings:
            applicable.append(("headings", head_seq))
        if pdf_doc.lists:
            applicable.append(("lists", list_seq))
        if pdf_doc.tables:
            applicable.append(("tables", table_seq))
        if pdf_doc.headers_footers:
            applicable.append(("headers_footers", hf_score))

        total_w = sum(CONTENT_W[k] for k, _ in applicable)
        content_score = (sum(CONTENT_W[k] * v for k, v in applicable) / total_w) if applicable else 0.0

        content_detail = (
            f"text_seq={effective_text_seq:.1f} (coverage={text_coverage:.1f}) "
            f"front_page_seq={front_seq:.1f} (coverage={front_coverage:.1f}) "
            f"paragraphs={para_seq:.1f}({para_matched}) "
            f"headings={head_seq:.1f}({head_matched}) tables={table_seq:.1f} "
            f"lists={list_seq:.1f}({list_matched}) hf={hf_score:.1f}"
        )
        content_fail_reason = ""
        if pdf_doc.tables and not word_doc.tables and effective_text_seq < 70.0:
            content_fail_reason = (f"PDF contains {len(pdf_doc.tables)} table(s) but the "
                                   f"candidate has no tables - content structure mismatch.")
        elif effective_text_seq < TEXT_SEQ_REJECT_MIN:
            content_fail_reason = f"Ordered content sequence match is too low ({effective_text_seq:.1f}%)."
        elif content_score < CONTENT_REJECT_MIN and effective_text_seq < 50.0:
            content_fail_reason = f"Exact content verification failed ({content_score:.1f}% < {CONTENT_REJECT_MIN:.0f}%)."

        content_passed = not content_fail_reason
        stage_reports.append(StageReport(
            stage="Stage 3 - Exact Content Verification",
            score=round(content_score, 2),
            passed=content_passed,
            detail=content_detail,
            effect="" if content_passed else "Candidate rejected"
        ))
        if not content_passed:
            rejected = True
            rejected_reason = content_fail_reason

        # --- Stage 4: Structural Verification ------------------------------
        page_sim = count_ratio(pdf_doc.page_count, word_doc.page_count)
        if matched_ref_codes or max(text_coverage, front_coverage, best_page_cov) >= 20.0:
            page_sim = max(page_sim, 90.0)
        section_sim = count_ratio(pdf_doc.section_count, word_doc.section_count)
        table_count_sim = count_ratio(len(pdf_doc.tables), len(word_doc.tables))
        heading_count_sim = count_ratio(len(pdf_doc.headings), len(word_doc.headings))
        structure_score = (page_sim + section_sim + table_count_sim + heading_count_sim) / 4.0

        structure_detail = (
            f"pages {pdf_doc.page_count} vs {word_doc.page_count} ({page_sim:.1f}%) | "
            f"sections {pdf_doc.section_count} vs {word_doc.section_count} ({section_sim:.1f}%) | "
            f"tables {len(pdf_doc.tables)} vs {len(word_doc.tables)} ({table_count_sim:.1f}%) | "
            f"headings {len(pdf_doc.headings)} vs {len(word_doc.headings)} ({heading_count_sim:.1f}%)"
        )
        stage_reports.append(StageReport(
            stage="Stage 4 - Structural Verification",
            score=round(structure_score, 2),
            passed=True,
            detail=structure_detail,
            effect="Reduces confidence score" if structure_score < 90.0 else "None"
        ))

        # --- Stage 5: Semantic Verification (gated by structure) -----------
        if rejected:
            semantic_score = 0.0
            sem_effect = "Skipped (candidate already rejected in Stage 3)"
        else:
            if precomputed_semantic_score is not None:
                semantic_score = precomputed_semantic_score
            else:
                semantic_score = self.semantic_matcher.compute_semantic_similarity(
                    pdf_doc.full_text, word_doc.full_text
                )
            sem_effect = "None"
            if structure_score < STRUCTURE_GATE:
                sem_effect = (f"Gated - structure ({structure_score:.1f}%) below {STRUCTURE_GATE:.0f}%, "
                              f"semantic cannot override structural mismatch")

        stage_reports.append(StageReport(
            stage="Stage 5 - Semantic Verification",
            score=round(semantic_score, 2),
            passed=not rejected,
            detail=f"semantic={semantic_score:.1f} structure_gate={STRUCTURE_GATE:.0f}%",
            effect=sem_effect
        ))

        # --- Source Verification: is this the perfect document for the PDF? --
        pdf_norm_len = len(normalize_text(pdf_doc.full_text))
        front_norm_len = len(normalize_text(pdf_front_text))
        effective_norm_len = max(pdf_norm_len, front_norm_len) if pdf_front_text else pdf_norm_len
        page_relationship_ok = (
            page_sim >= SOURCE_PAGE_SIM_MIN
            or pdf_doc.page_count <= word_doc.page_count
            or word_doc.page_count <= pdf_doc.page_count
            or max(text_coverage, front_coverage, best_page_cov) >= 20.0
            or bool(matched_ref_codes)
        )
        front_page_verified = (
            front_coverage >= SOURCE_COVERAGE_MIN
            and front_norm_len >= SOURCE_MIN_PDF_CHARS
        )
        full_doc_verified = (
            text_coverage >= 20.0
            and pdf_norm_len >= SOURCE_MIN_PDF_CHARS
        )
        ref_code_verified = bool(matched_ref_codes)
        best_page_verified = (best_page_cov >= 40.0)

        verified_source = (
            not rejected
            and (front_page_verified or full_doc_verified or ref_code_verified or best_page_verified)
            and page_relationship_ok
            and effective_norm_len >= SOURCE_MIN_PDF_CHARS
        )

        # --- Final score composition ---------------------------------------
        is_exact_match = verified_source or (content_score >= 96.0 and structure_score >= 85.0
                          and semantic_score >= 90.0 and page_sim >= 70.0)
        if is_exact_match or verified_source:
            overall_score = 100.0
            confidence = 100.0
            match_category = "100% Content Match (Original Source)"
            match_basis = "protocol reference ID / template containment" if ref_code_verified else ("best page" if best_page_verified else "full document")
        else:
            overall_score = (content_score * 0.50) + (structure_score * 0.25) + (semantic_score * 0.15) + (hf_score * 0.10)
            if structure_score < STRUCTURE_GATE:
                overall_score = min(overall_score, STRUCTURE_CAP)
            if content_score < 50.0:
                overall_score = min(overall_score, CONTENT_CAP)
            overall_score = float(min(99.9, max(0.0, overall_score)))

            # Large structural differences must reduce the confidence score
            confidence = overall_score * (0.55 + 0.45 * (structure_score / 100.0))
            confidence = float(min(100.0, max(0.0, confidence)))

            if overall_score >= 95.0:
                match_category = "95-99% Match (Near-Identical Document)"
            elif overall_score >= 90.0:
                match_category = "90-94% Match (Highly Similar Document)"
            else:
                match_category = "Standard Match"
            match_basis = ""

        verify_basis_detail = (
            f"front page coverage {front_coverage:.1f}%, full doc coverage {text_coverage:.1f}%"
        )
        stage_reports.append(StageReport(
            stage="Source Verification",
            score=round(max(front_coverage, text_coverage), 2),
            passed=verified_source,
            detail=(f"{verify_basis_detail}; page relationship: pdf {pdf_doc.page_count}p vs "
                    f"word {word_doc.page_count}p (page sim {page_sim:.1f}%)") if verified_source
                   else (f"{verify_basis_detail} (need >= {SOURCE_COVERAGE_MIN:.0f}% on the front "
                         f"page or full document)"
                         + ("" if page_relationship_ok else
                            f"; page relationship not plausible (sim {page_sim:.1f}% < "
                            f"{SOURCE_PAGE_SIM_MIN:.0f}%, pdf {pdf_doc.page_count}p vs "
                            f"word {word_doc.page_count}p)")),
            effect=f"Candidate verified as the perfect original source (matched by {match_basis})" if verified_source else "None"
        ))

        if verified_source:
            overall_score = 100.0
            confidence = 100.0
            match_category = "PERFECT ORIGINAL SOURCE MATCH (Verified)"

        selection_reason = ""
        if not rejected:
            if verified_source:
                coverage_label = (
                    f"front page coverage {front_coverage:.1f}%" if match_basis == "front page"
                    else f"coverage {text_coverage:.1f}%"
                )
                selection_reason = (
                    f"Verified perfect match (matched by {match_basis}): {coverage_label} of the PDF "
                    f"appears in exact order inside this Word document (pages {pdf_doc.page_count} vs "
                    f"{word_doc.page_count}). This is the original source of the uploaded PDF."
                )
            else:
                selection_reason = (
                    f"Best candidate: content sequence {content_score:.1f}% "
                    f"(front page {front_seq:.1f}%), structure {structure_score:.1f}%, "
                    f"semantic {semantic_score:.1f}%; final validation passed."
                )

        # --- Matching pages & sections (informational) ---------------------
        matching_pages = []
        w_sample = word_doc.full_text[:1500]
        for p in pdf_doc.pages:
            p_score = self.text_matcher.compute_text_similarity(p.text[:1000], w_sample)
            if p_score >= 40.0:
                matching_pages.append(p.page_num)
        if not matching_pages and pdf_doc.page_count > 0:
            matching_pages = [1]

        matching_sections = []
        for h in pdf_doc.headings[:15]:
            for wh in word_doc.headings[:20]:
                if self.text_matcher.compute_text_similarity(h, wh) >= 65.0:
                    matching_sections.append(h)
                    break

        dt_str = datetime.datetime.fromtimestamp(word_doc.last_modified).strftime("%Y-%m-%d %H:%M")
        size_str = format_file_size(word_doc.file_size)

        component_scores = {
            "text": text_seq,
            "semantic": semantic_score,
            "headings": head_seq,
            "paragraphs": para_seq,
            "tables": table_seq,
            "keywords": keyword_score,
            "structure": structure_score,
            "section": section_sim,
            "page_sequence": page_sim,
            "headers_footers": hf_score,
            "coverage": text_coverage,
        }

        return MatchResult(
            word_file_name=word_doc.filename,
            file_path=word_doc.filepath,
            folder_name=word_doc.folder_name,
            overall_score=round(overall_score, 2),
            confidence_score=round(confidence, 2),
            component_scores={k: round(v, 2) for k, v in component_scores.items()},
            matching_pages=matching_pages,
            matching_sections=matching_sections[:10],
            last_modified_date=dt_str,
            file_size_str=size_str,
            match_category=match_category,
            content_score=round(content_score, 2),
            structure_score=round(structure_score, 2),
            semantic_score=round(semantic_score, 2),
            table_score=round(table_seq, 2),
            header_footer_score=round(hf_score, 2),
            selection_reason=selection_reason,
            rejected=rejected,
            rejected_reason=rejected_reason,
            verified_source=verified_source,
            text_coverage=round(text_coverage, 2),
            front_coverage=round(front_coverage, 2),
            match_basis=match_basis,
            stage_reports=stage_reports,
            debug_stages=[
                {"stage": r.stage, "score": r.score, "passed": r.passed,
                 "detail": r.detail, "effect": r.effect}
                for r in stage_reports
            ]
        )

    # ------------------------------------------------------------------
    # Batch entry point
    # ------------------------------------------------------------------
    def compare_batch(
        self,
        pdf_doc: DocumentFeatures,
        word_docs: List[DocumentFeatures],
        max_workers: int = 8,
        top_k: int = 20,
        compare_all: bool = True,
        max_candidates: int = 5,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> List[MatchResult]:
        """Stage 2-6 retrieval pipeline over the indexed corpus. Accepted
        candidates are returned ranked first; rejected candidates follow with
        their rejection reason so the UI can explain why they were skipped.

        By default (compare_all=True) the Top-5 retrieved candidates are deeply
        compared - retrieval ranks every document cheaply, so the true original
        source (which ranks at/near #1) is captured. max_candidates raises the
        pool (e.g. 500 for exhaustive mode). Set compare_all=False for the
        legacy Top-k mode."""
        if not word_docs:
            return []

        pool_size = min(max_candidates, len(word_docs)) if compare_all else max(1, top_k)
        candidates, semantic_scores = self.retrieve_candidates(
            pdf_doc, word_docs, top_k=pool_size, return_scores=True
        )

        results: List[MatchResult] = [None] * len(candidates)

        def worker(index: int, word_doc: DocumentFeatures, sem_score: float):
            return index, self.compare(pdf_doc, word_doc, precomputed_semantic_score=sem_score)

        workers = min(max_workers, len(candidates))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(worker, idx, doc, semantic_scores[idx])
                for idx, doc in enumerate(candidates)
            ]
            completed = 0
            for future in as_completed(futures):
                idx, res = future.result()
                results[idx] = res
                completed += 1
                if progress_callback:
                    progress_callback(completed, len(candidates), res.word_file_name)

        accepted = sorted(
            [r for r in results if not r.rejected],
            key=lambda r: (r.overall_score, r.content_score, r.structure_score),
            reverse=True
        )
        rejected_list = sorted(
            [r for r in results if r.rejected],
            key=lambda r: r.overall_score,
            reverse=True
        )

        exact_matches = [r for r in accepted if r.overall_score >= 100.0]
        if exact_matches:
            logger.info(f"Final Decision: located true 100% Original Word Source Document -> {exact_matches[0].word_file_name}")

        return accepted + rejected_list

    @staticmethod
    def _keyword_jaccard(kw1, kw2) -> float:
        if not kw1 or not kw2:
            return 0.0
        union = kw1 | kw2
        if not union:
            return 0.0
        return (len(kw1 & kw2) / len(union)) * 100.0