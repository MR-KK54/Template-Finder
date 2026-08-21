import os
import time
from typing import List, Callable, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from src.database import IndexDatabase
from src.extractors.docx_extractor import DocxExtractor
from src.indexer.file_scanner import FileScanner
from src.models import DocumentFeatures
from src.utils.file_utils import compute_file_hash, to_long_path
from src.utils.logger import get_logger
from src.config import SUPPORTED_WORD_EXTENSIONS, INDEX_VERSION

logger = get_logger("index_manager")

class WordFileWatchHandler(FileSystemEventHandler):
    def __init__(self, index_manager):
        super().__init__()
        self.index_manager = index_manager

    def on_created(self, event):
        if not event.is_directory and os.path.splitext(event.src_path)[1].lower() in SUPPORTED_WORD_EXTENSIONS:
            logger.info(f"File created event: {event.src_path}")
            self.index_manager.index_single_file(event.src_path)

    def on_modified(self, event):
        if not event.is_directory and os.path.splitext(event.src_path)[1].lower() in SUPPORTED_WORD_EXTENSIONS:
            logger.info(f"File modified event: {event.src_path}")
            self.index_manager.index_single_file(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory and os.path.splitext(event.src_path)[1].lower() in SUPPORTED_WORD_EXTENSIONS:
            logger.info(f"File deleted event: {event.src_path}")
            self.index_manager.remove_single_file(event.src_path)

class IndexManager:
    """Manages incremental multi-threaded document indexing and live directory monitoring."""

    def __init__(self, db: Optional[IndexDatabase] = None):
        self.db = db or IndexDatabase()
        self.extractor = DocxExtractor()
        self.scanner = FileScanner()
        self.observer: Optional[Observer] = None

    def index_directory(
        self,
        folder_path: str,
        recursive: bool = True,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        max_workers: int = 12
    ) -> List[DocumentFeatures]:
        """Scans and indexes directory incrementally with multi-threading."""
        start_time = time.time()
        filepaths = self.scanner.scan_directory(folder_path, recursive=recursive)
        total = len(filepaths)

        # Prune stale / moved / duplicate index entries so the index reflects
        # exactly the files present in the selected folder right now.
        self.db.prune_index(set(filepaths))

        if total == 0:
            if progress_callback:
                progress_callback(0, 0, "No Word files found.")
            return self.db.get_all_documents()

        files_to_index = []
        force_reindex = self.db.get_index_version() < INDEX_VERSION
        if force_reindex:
            logger.info(f"Index feature version mismatch (stored {self.db.get_index_version()}, "
                        f"current {INDEX_VERSION}) - forcing full re-index.")
        for fp in filepaths:
            try:
                long_fp = to_long_path(fp)
                if not os.path.exists(long_fp) and not os.path.exists(fp):
                    logger.warning(f"Skipping non-existent file: {fp}")
                    continue
                target = long_fp if os.path.exists(long_fp) else fp
                mtime = os.path.getmtime(target)
                if force_reindex:
                    # Re-parsing everything anyway - skip hashing entirely
                    files_to_index.append(fp)
                    continue
                size = os.path.getsize(target)
                if self.db.is_file_unchanged_by_meta(fp, mtime, size):
                    # mtime + size unchanged - content is effectively the same
                    continue
                f_hash = compute_file_hash(fp)
                if not self.db.is_file_up_to_date(fp, mtime, f_hash, size):
                    files_to_index.append(fp)
            except Exception as e:
                logger.warning(f"Skipping unreadable or inaccessible file {fp}: {e}")

        logger.info(f"Indexing status: Total files = {total}, Needs parsing/re-index = {len(files_to_index)}")

        if files_to_index:
            indexed_count = 0
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_file = {executor.submit(self._parse_and_cache, fp): fp for fp in files_to_index}
                for future in as_completed(future_to_file):
                    fp = future_to_file[future]
                    indexed_count += 1
                    try:
                        future.result()
                    except Exception as e:
                        logger.error(f"Error indexing {fp}: {e}")

                    if progress_callback:
                        progress_callback(indexed_count, len(files_to_index), f"Indexed {os.path.basename(fp)}")
        else:
            if progress_callback:
                progress_callback(total, total, "All document indexes are up to date.")

        # Persist the current feature version so future searches reuse the cache
        self.db.set_index_version(INDEX_VERSION)

        elapsed = time.time() - start_time
        logger.info(f"Directory index process finished in {elapsed:.2f} seconds.")

        # Start watchdog live observer
        self.start_watching(folder_path)

        return self.db.get_all_documents()

    def _parse_and_cache(self, filepath: str) -> DocumentFeatures:
        doc = self.extractor.extract(filepath)
        # Precompute and cache the semantic embedding at index time so
        # retrieval never re-encodes the whole corpus at query time.
        if doc is not None and not doc.embedding_json and doc.full_text:
            try:
                from src.matcher.semantic_matcher import SemanticMatcher
                matcher = getattr(self, "_semantic_matcher", None)
                if matcher is None:
                    matcher = SemanticMatcher()
                    self._semantic_matcher = matcher
                emb = matcher.compute_embedding(doc.full_text)
                if emb:
                    import json
                    doc.embedding_json = json.dumps(emb)
            except Exception as e:
                logger.warning(f"Could not precompute embedding for {filepath}: {e}")
        self.db.save_document(doc)
        return doc

    def index_single_file(self, filepath: str):
        try:
            if not filepath.startswith("~$"):
                self._parse_and_cache(filepath)
        except Exception as e:
            logger.error(f"Failed to index single file {filepath}: {e}")

    def remove_single_file(self, filepath: str):
        try:
            self.db.remove_document(filepath)
        except Exception as e:
            logger.error(f"Failed to remove file from index {filepath}: {e}")

    def start_watching(self, folder_path: str):
        """Starts live Watchdog directory watcher."""
        if self.observer:
            try:
                self.observer.stop()
                self.observer.join()
            except Exception:
                pass

        try:
            handler = WordFileWatchHandler(self)
            self.observer = Observer()
            self.observer.schedule(handler, folder_path, recursive=True)
            self.observer.start()
            logger.info(f"Started Watchdog live observer on {folder_path}")
        except Exception as e:
            logger.warning(f"Could not start Watchdog observer on {folder_path}: {e}")

    def stop_watching(self):
        if self.observer:
            try:
                self.observer.stop()
                self.observer.join()
            except Exception:
                pass
            self.observer = None
