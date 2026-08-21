import sqlite3
import json
import os
from typing import Optional, List, Dict, Any, Set
from src.config import DB_PATH
from src.models import DocumentFeatures, TableData, PageData
from src.utils.file_utils import canonical_path
from src.utils.logger import get_logger

logger = get_logger("database")

class IndexDatabase:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Creates table schema if not exists."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS word_index (
                filepath TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                folder_name TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                last_modified REAL NOT NULL,
                file_hash TEXT NOT NULL,
                page_count INTEGER DEFAULT 1,
                indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS document_features (
                filepath TEXT PRIMARY KEY,
                full_text TEXT,
                headings_json TEXT,
                paragraphs_json TEXT,
                tables_json TEXT,
                lists_json TEXT,
                keywords_json TEXT,
                pages_json TEXT,
                section_count INTEGER DEFAULT 1,
                fingerprint TEXT DEFAULT '',
                FOREIGN KEY (filepath) REFERENCES word_index (filepath) ON DELETE CASCADE
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS document_embeddings (
                filepath TEXT PRIMARY KEY,
                embedding_json TEXT,
                FOREIGN KEY (filepath) REFERENCES word_index (filepath) ON DELETE CASCADE
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """)
            conn.commit()
        finally:
            conn.close()
        self._ensure_columns()

    def _ensure_columns(self):
        """Migrates older database schemas by adding missing columns."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(document_features)")
            existing = {row[1] for row in cursor.fetchall()}
            if "section_count" not in existing:
                cursor.execute("ALTER TABLE document_features ADD COLUMN section_count INTEGER DEFAULT 1")
            if "fingerprint" not in existing:
                cursor.execute("ALTER TABLE document_features ADD COLUMN fingerprint TEXT DEFAULT ''")
            conn.commit()
        except Exception as e:
            logger.warning(f"Schema migration skipped: {e}")
        finally:
            conn.close()

    def get_index_version(self) -> int:
        """Returns the stored index feature version (0 if never set)."""
        conn = self._get_connection()
        try:
            row = conn.execute("SELECT value FROM meta WHERE key = 'index_version'").fetchone()
            return int(row["value"]) if row and row["value"] else 0
        except Exception:
            return 0
        finally:
            conn.close()

    def set_index_version(self, version: int):
        conn = self._get_connection()
        try:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('index_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(version),)
            )
            conn.commit()
        except Exception as e:
            logger.warning(f"Could not persist index version: {e}")
        finally:
            conn.close()

    def is_file_unchanged_by_meta(self, filepath: str, mtime: float, file_size: int) -> bool:
        """Fast check: if a row exists and both mtime and size are unchanged, the
        file content is almost certainly identical - avoids hashing large files
        on every search (only recomputed when mtime/size differ)."""
        key = canonical_path(filepath)
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT last_modified, file_size FROM word_index WHERE filepath = ?",
                (key,)
            )
            row = cursor.fetchone()
            if not row:
                return False
            return (abs(row["last_modified"] - mtime) < 1.0
                    and row["file_size"] == file_size)
        finally:
            conn.close()

    def is_file_up_to_date(self, filepath: str, mtime: float, file_hash: str, file_size: int = None) -> bool:
        """Checks if file index entry exists and has not been modified."""
        key = canonical_path(filepath)
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT last_modified, file_hash, file_size FROM word_index WHERE filepath = ?",
                (key,)
            )
            row = cursor.fetchone()
            if not row:
                return False
            if abs(row["last_modified"] - mtime) >= 1.0:
                return False
            if file_size is not None and row["file_size"] == file_size:
                return True
            return row["file_hash"] == file_hash
        finally:
            conn.close()

    def prune_index(self, valid_paths: Set[str]):
        """Removes index rows whose canonical filepath is no longer present
        in the currently scanned directory (stale or moved files)."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT filepath FROM word_index")
            rows = cursor.fetchall()
            to_remove = [r["filepath"] for r in rows if canonical_path(r["filepath"]) not in valid_paths]
            for path in to_remove:
                cursor.execute("DELETE FROM word_index WHERE filepath = ?", (path,))
            if to_remove:
                logger.info(f"Pruned {len(to_remove)} stale index entrie(s) no longer present in the scanned folder.")
            conn.commit()
        finally:
            conn.close()

    def save_document(self, doc: DocumentFeatures):
        """Inserts or updates document metadata and extracted features in cache DB."""
        doc.filepath = canonical_path(doc.filepath)
        tables_json = json.dumps([
            {"rows": t.rows, "cols": t.cols, "headers": t.headers, "cell_text": t.cell_text, "flat_text": t.flat_text}
            for t in doc.tables
        ], ensure_ascii=False)

        pages_json = json.dumps([
            {
                "page_num": p.page_num,
                "text": p.text,
                "headings": p.headings,
                "tables": [
                    {"rows": t.rows, "cols": t.cols, "headers": t.headers, "cell_text": t.cell_text, "flat_text": t.flat_text}
                    for t in p.tables
                ],
                "is_scanned": p.is_scanned
            }
            for p in doc.pages
        ], ensure_ascii=False)

        headings_json = json.dumps(doc.headings, ensure_ascii=False)
        paragraphs_json = json.dumps(doc.paragraphs, ensure_ascii=False)
        lists_json = json.dumps(doc.lists, ensure_ascii=False)
        keywords_json = json.dumps(list(doc.keywords), ensure_ascii=False)

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO word_index (filepath, filename, folder_name, file_size, last_modified, file_hash, page_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(filepath) DO UPDATE SET
                    filename=excluded.filename,
                    folder_name=excluded.folder_name,
                    file_size=excluded.file_size,
                    last_modified=excluded.last_modified,
                    file_hash=excluded.file_hash,
                    page_count=excluded.page_count,
                    indexed_at=CURRENT_TIMESTAMP
            """, (
                doc.filepath, doc.filename, doc.folder_name, doc.file_size,
                doc.last_modified, doc.file_hash, doc.page_count
            ))

            cursor.execute("""
                INSERT INTO document_features (filepath, full_text, headings_json, paragraphs_json, tables_json, lists_json, keywords_json, pages_json, section_count, fingerprint)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(filepath) DO UPDATE SET
                    full_text=excluded.full_text,
                    headings_json=excluded.headings_json,
                    paragraphs_json=excluded.paragraphs_json,
                    tables_json=excluded.tables_json,
                    lists_json=excluded.lists_json,
                    keywords_json=excluded.keywords_json,
                    pages_json=excluded.pages_json,
                    section_count=excluded.section_count,
                    fingerprint=excluded.fingerprint
            """, (
                doc.filepath, doc.full_text, headings_json, paragraphs_json,
                tables_json, lists_json, keywords_json, pages_json,
                doc.section_count, doc.fingerprint
            ))

            if doc.embedding_json:
                cursor.execute("""
                    INSERT INTO document_embeddings (filepath, embedding_json)
                    VALUES (?, ?)
                    ON CONFLICT(filepath) DO UPDATE SET embedding_json=excluded.embedding_json
                """, (doc.filepath, doc.embedding_json))

            conn.commit()
        finally:
            conn.close()

    def remove_document(self, filepath: str):
        """Removes a deleted file from index."""
        key = canonical_path(filepath)
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM word_index WHERE filepath = ?", (key,))
            conn.commit()
        finally:
            conn.close()

    def get_all_documents(self) -> List[DocumentFeatures]:
        """Retrieves all indexed document features from SQLite (deduplicated by file hash)."""
        docs = []
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT wi.filepath, wi.filename, wi.folder_name, wi.file_size, wi.last_modified, wi.file_hash, wi.page_count,
                       df.full_text, df.headings_json, df.paragraphs_json, df.tables_json, df.lists_json, df.keywords_json, df.pages_json,
                       df.section_count, df.fingerprint,
                       de.embedding_json
                FROM word_index wi
                JOIN document_features df ON wi.filepath = df.filepath
                LEFT JOIN document_embeddings de ON wi.filepath = de.filepath
                ORDER BY wi.last_modified DESC
            """)
            # Deduplicate by file hash. The same physical file can have multiple rows
            # (e.g. different path casing or older extraction runs); keep the row with
            # the most complete full_text so stale, header-less extractions never win.
            best_by_hash: dict = {}
            for row in cursor.fetchall():
                file_hash = row["file_hash"] or ""
                cur = best_by_hash.get(file_hash)
                if cur is None or len(row["full_text"] or "") > len(cur["full_text"] or ""):
                    best_by_hash[file_hash] = row
            for row in best_by_hash.values():
                try:
                    tables_raw = json.loads(row["tables_json"] or "[]")
                    tables = [
                        TableData(
                            rows=t.get("rows", 0),
                            cols=t.get("cols", 0),
                            headers=t.get("headers", []),
                            cell_text=t.get("cell_text", []),
                            flat_text=t.get("flat_text", "")
                        ) for t in tables_raw
                    ]

                    pages_raw = json.loads(row["pages_json"] or "[]")
                    pages = []
                    for p in pages_raw:
                        p_tables = [
                            TableData(
                                rows=t.get("rows", 0),
                                cols=t.get("cols", 0),
                                headers=t.get("headers", []),
                                cell_text=t.get("cell_text", []),
                                flat_text=t.get("flat_text", "")
                            ) for t in p.get("tables", [])
                        ]
                        pages.append(PageData(
                            page_num=p.get("page_num", 1),
                            text=p.get("text", ""),
                            headings=p.get("headings", []),
                            tables=p.tables if hasattr(p, 'tables') else p_tables,
                            is_scanned=p.get("is_scanned", False)
                        ))

                    doc = DocumentFeatures(
                        filepath=row["filepath"],
                        filename=row["filename"],
                        folder_name=row["folder_name"],
                        file_size=row["file_size"],
                        last_modified=row["last_modified"],
                        file_hash=row["file_hash"],
                        page_count=row["page_count"],
                        section_count=row["section_count"] or 1,
                        full_text=row["full_text"] or "",
                        headings=json.loads(row["headings_json"] or "[]"),
                        paragraphs=json.loads(row["paragraphs_json"] or "[]"),
                        tables=tables,
                        lists=json.loads(row["lists_json"] or "[]"),
                        keywords=set(json.loads(row["keywords_json"] or "[]")),
                        pages=pages,
                        embedding_json=row["embedding_json"],
                        fingerprint=row["fingerprint"] or ""
                    )
                    docs.append(doc)
                except Exception as e:
                    logger.error(f"Error loading indexed doc {row['filepath']}: {e}")
        finally:
            conn.close()
        return docs
