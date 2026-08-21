import time
from typing import List
from PySide6.QtCore import QThread, Signal
from src.indexer.index_manager import IndexManager
from src.extractors.pdf_extractor import PDFExtractor
from src.matcher.hybrid_comparator import HybridComparator
from src.models import DocumentFeatures, MatchResult
from src.utils.logger import get_logger

logger = get_logger("ui_workers")

class IndexWorker(QThread):
    progress_signal = Signal(int, int, str)
    finished_signal = Signal(list)
    error_signal = Signal(str)

    def __init__(self, folder_path: str, recursive: bool = True):
        super().__init__()
        self.folder_path = folder_path
        self.recursive = recursive
        self.index_manager = IndexManager()

    def run(self):
        try:
            def cb(current, total, msg):
                self.progress_signal.emit(current, total, msg)

            docs = self.index_manager.index_directory(
                folder_path=self.folder_path,
                recursive=self.recursive,
                progress_callback=cb
            )
            self.finished_signal.emit(docs)
        except Exception as e:
            logger.error(f"IndexWorker error: {e}")
            self.error_signal.emit(str(e))

class SearchWorker(QThread):
    progress_signal = Signal(int, int, str)
    finished_signal = Signal(list, float, bool)  # results, elapsed_sec, is_scanned
    error_signal = Signal(str)

    def __init__(self, pdf_path: str, threshold: float = 70.0, front_page_only: bool = False):
        super().__init__()
        self.pdf_path = pdf_path
        self.threshold = threshold
        self.front_page_only = front_page_only
        self.pdf_extractor = PDFExtractor()
        self.comparator = HybridComparator()
        self.index_manager = IndexManager()

    def run(self):
        try:
            start_time = time.time()
            self.progress_signal.emit(10, 100, "Extracting PDF text & structural features...")

            pdf_doc = self.pdf_extractor.extract(self.pdf_path)

            self.progress_signal.emit(30, 100, "Loading indexed Word templates from cache...")
            word_docs = self.index_manager.db.get_all_documents()
            total_word_docs = len(word_docs)

            if total_word_docs == 0:
                self.progress_signal.emit(100, 100, "No indexed Word templates available.")
                self.finished_signal.emit([], time.time() - start_time, pdf_doc.is_scanned_pdf)
                return

            self.progress_signal.emit(50, 100, "Comparing templates in parallel...")
            all_match_results = self.comparator.compare_batch(pdf_doc, word_docs)
            results = [r for r in all_match_results if not r.rejected and (r.overall_score >= self.threshold or r.verified_source)]
            if self.front_page_only:
                results = [r for r in results if r.verified_source and r.match_basis in ("front page", "both")]
            results.sort(key=lambda x: x.overall_score, reverse=True)

            elapsed = time.time() - start_time
            self.progress_signal.emit(100, 100, f"Search completed in {elapsed:.2f}s.")
            self.finished_signal.emit(results, elapsed, pdf_doc.is_scanned_pdf)
        except Exception as e:
            logger.error(f"SearchWorker error: {e}")
            self.error_signal.emit(str(e))
