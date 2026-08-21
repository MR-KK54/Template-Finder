import os
import fitz  # PyMuPDF
from typing import Tuple, List, Set, Dict, Any
from src.models import DocumentFeatures, PageData, TableData
from src.extractors.ocr_engine import OCREngine
from src.indexer.fingerprint import build_fingerprint
from src.utils.logger import get_logger
from src.utils.file_utils import canonical_path, compute_file_hash, to_long_path

logger = get_logger("pdf_extractor")

class PDFExtractor:
    def __init__(self, ocr_engine: Optional[OCREngine] = None):
        self.ocr_engine = ocr_engine or OCREngine()

    def extract(self, filepath: str) -> DocumentFeatures:
        """Extracts complete structural and textual features from a PDF file."""
        long_filepath = to_long_path(filepath)
        target_path = long_filepath if os.path.exists(long_filepath) else filepath

        if not os.path.exists(target_path):
            raise FileNotFoundError(f"PDF file not found: {filepath}")

        canonical = canonical_path(filepath)
        filename = os.path.basename(canonical)
        folder_name = os.path.basename(os.path.dirname(canonical))

        try:
            file_size = os.path.getsize(target_path)
            last_modified = os.path.getmtime(target_path)
        except Exception:
            file_size = 0
            last_modified = 0.0

        file_hash = compute_file_hash(filepath)

        doc = fitz.open(target_path)
        page_count = len(doc)

        # Lazy pdfplumber fallback for table extraction when PyMuPDF finds none
        pdfplumber_pdf = None
        pdfplumber_pages = None

        pages: List[PageData] = []
        all_headings: List[str] = []
        all_paragraphs: List[str] = []
        all_tables: List[TableData] = []
        all_lists: List[str] = []
        all_keywords: Set[str] = set()
        is_document_scanned = False
        full_text_chunks: List[str] = []

        for page_idx in range(page_count):
            page = doc[page_idx]
            page_text = page.get_text("text").strip()

            # Scanned page detection heuristic
            images = page.get_images()
            is_scanned = False
            if (len(page_text) < 150 and len(images) > 0) or len(page_text) < 20:
                is_scanned = True
                is_document_scanned = True

            if is_scanned:
                logger.info(f"Page {page_idx + 1} of {filename} detected as scanned. Triggering OCR...")
                pix = page.get_pixmap(dpi=150)
                img_bytes = pix.tobytes("png")
                ocr_text = self.ocr_engine.perform_ocr_on_image(img_bytes)
                if ocr_text and ocr_text.strip():
                    if len(ocr_text.strip()) > len(page_text):
                        page_text = ocr_text.strip()
                    else:
                        page_text = (page_text + "\n" + ocr_text.strip()).strip()

            # Page Headings & Structure Extraction via PyMuPDF Blocks / Spans
            page_headings, page_paras, page_lists = self._parse_page_blocks(page, page_text)

            # Table extraction using PyMuPDF (find_tables)
            page_tables = self._extract_page_tables(page)

            # Fallback: pdfplumber table finder when PyMuPDF finds nothing
            if not page_tables:
                if pdfplumber_pages is None:
                    try:
                        import pdfplumber
                        pdfplumber_pdf = pdfplumber.open(target_path)
                        pdfplumber_pages = pdfplumber_pdf.pages
                    except Exception as e:
                        logger.warning(f"pdfplumber fallback unavailable: {e}")
                        pdfplumber_pages = []
                if pdfplumber_pages and page_idx < len(pdfplumber_pages):
                    page_tables = self._extract_page_tables_pdfplumber(pdfplumber_pages[page_idx])

            page_data = PageData(
                page_num=page_idx + 1,
                text=page_text,
                headings=page_headings,
                tables=page_tables,
                is_scanned=is_scanned
            )
            pages.append(page_data)

            all_headings.extend(page_headings)
            all_paragraphs.extend(page_paras)
            all_lists.extend(page_lists)
            all_tables.extend(page_tables)
            if page_text:
                full_text_chunks.append(page_text)

            # Extract basic keywords (tokens with len >= 4)
            words = [w.lower().strip(".,!?;:()[]\"'") for w in page_text.split()]
            all_keywords.update([w for w in words if len(w) >= 4 and w.isalpha()])

        doc.close()
        if pdfplumber_pdf is not None:
            try:
                pdfplumber_pdf.close()
            except Exception:
                pass
        full_text = "\n\n".join(full_text_chunks)

        # Estimated section count (consistent with Word extractor): one section
        # per heading-like block plus the document body.
        section_count = max(1, len(all_headings) + 1)

        pdf_features = DocumentFeatures(
            filepath=canonical,
            filename=filename,
            folder_name=folder_name,
            file_size=file_size,
            last_modified=last_modified,
            file_hash=file_hash,
            full_text=full_text,
            headings=all_headings,
            paragraphs=all_paragraphs,
            tables=all_tables,
            lists=all_lists,
            keywords=all_keywords,
            page_count=page_count,
            section_count=section_count,
            pages=pages,
            is_scanned_pdf=is_document_scanned
        )
        pdf_features.fingerprint = build_fingerprint(pdf_features)
        return pdf_features

    def _parse_page_blocks(self, page: fitz.Page, page_text: str) -> Tuple[List[str], List[str], List[str]]:
        """Parses page text blocks to identify headings, paragraphs, and list items."""
        headings = []
        paras = []
        lists = []

        try:
            dict_blocks = page.get_text("dict")["blocks"]
            for b in dict_blocks:
                if b.get("type") == 0:  # Text block
                    block_text = ""
                    max_font_size = 0.0
                    is_bold = False

                    for line in b.get("lines", []):
                        for span in line.get("spans", []):
                            span_text = span.get("text", "").strip()
                            if span_text:
                                block_text += " " + span_text
                                font_size = span.get("size", 0.0)
                                if font_size > max_font_size:
                                    max_font_size = font_size
                                flags = span.get("flags", 0)
                                if flags & 2:  # bold flag
                                    is_bold = True

                    clean_block = block_text.strip()
                    if not clean_block:
                        continue

                    # Heuristic: Larger font size or bold short line = Heading
                    if max_font_size >= 13.0 or (is_bold and len(clean_block.split()) < 12):
                        headings.append(clean_block)
                    elif clean_block.startswith(("- ", "* ", "• ", "1.", "2.", "3.", "(a)", "(1)")):
                        lists.append(clean_block)
                    else:
                        paras.append(clean_block)
        except Exception as e:
            logger.warning(f"Fallback to line-by-line block parsing: {e}")
            for line in page_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.isupper() and len(line.split()) < 10:
                    headings.append(line)
                elif line.startswith(("- ", "* ", "• ")) or (len(line) > 2 and line[0].isdigit() and line[1] in ".):"):
                    lists.append(line)
                else:
                    paras.append(line)

        return headings, paras, lists

    def _extract_page_tables(self, page: fitz.Page) -> List[TableData]:
        """Extracts tables from a PDF page using PyMuPDF table finder."""
        tables = []
        try:
            tabs = page.find_tables()
            if tabs and tabs.tables:
                for tab in tabs.tables:
                    raw_extract = tab.extract()
                    if not raw_extract:
                        continue
                    rows_cnt = len(raw_extract)
                    cols_cnt = len(raw_extract[0]) if rows_cnt > 0 else 0
                    headers = [str(c or "").strip() for c in raw_extract[0]] if rows_cnt > 0 else []
                    cell_text = [[str(c or "").strip() for c in r] for r in raw_extract]
                    flat_text = " ".join([c for r in cell_text for c in r if c])

                    tables.append(TableData(
                        rows=rows_cnt,
                        cols=cols_cnt,
                        headers=headers,
                        cell_text=cell_text,
                        flat_text=flat_text
                    ))
        except Exception as e:
            logger.warning(f"Error during PyMuPDF table extraction: {e}")
        return tables

    def _extract_page_tables_pdfplumber(self, pl_page) -> List[TableData]:
        """Fallback table extraction using pdfplumber when PyMuPDF finds none."""
        tables = []
        try:
            for tab in pl_page.find_tables():
                raw_extract = tab.extract()
                if not raw_extract:
                    continue
                rows_cnt = len(raw_extract)
                cols_cnt = len(raw_extract[0]) if rows_cnt > 0 else 0
                headers = [str(c or "").strip() for c in raw_extract[0]] if rows_cnt > 0 else []
                cell_text = [[str(c or "").strip() for c in r] for r in raw_extract]
                flat_text = " ".join([c for r in cell_text for c in r if c])

                tables.append(TableData(
                    rows=rows_cnt,
                    cols=cols_cnt,
                    headers=headers,
                    cell_text=cell_text,
                    flat_text=flat_text
                ))
        except Exception as e:
            logger.warning(f"Error during pdfplumber table extraction: {e}")
        return tables
