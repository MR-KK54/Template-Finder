import os
import tempfile
import fitz  # PyMuPDF
from src.extractors.pdf_extractor import PDFExtractor

def test_pdf_extraction():
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = os.path.join(tmpdir, "sample.pdf")
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "Master Service Agreement", fontsize=16)
        page.insert_text((50, 100), "1. Terms and Conditions of Service", fontsize=12)
        doc.save(pdf_path)
        doc.close()

        extractor = PDFExtractor()
        features = extractor.extract(pdf_path)

        assert features.filename == "sample.pdf"
        assert features.page_count == 1
        assert "Master Service Agreement" in features.full_text
        assert features.is_scanned_pdf is False
