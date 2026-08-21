import os
import json
import io
import tempfile
import pytest
from PIL import Image, ImageDraw
from src.extractors.ocr_engine import OCREngine
from src.matcher.semantic_matcher import SemanticMatcher
from src.matcher.hybrid_comparator import HybridComparator
from src.models import DocumentFeatures, PageData


def _make_doc(filepath: str, filename: str, full_text: str, embedding_json=None) -> DocumentFeatures:
    return DocumentFeatures(
        filepath=filepath,
        filename=filename,
        folder_name=os.path.basename(os.path.dirname(filepath)),
        file_size=5000,
        last_modified=1700000000.0,
        file_hash=os.path.basename(filepath),
        full_text=full_text,
        headings=[],
        paragraphs=[full_text],
        keywords=set(w for w in full_text.split() if len(w) >= 4),
        page_count=1,
        pages=[PageData(page_num=1, text=full_text, headings=[])],
        embedding_json=embedding_json,
    )


def test_ocr_engine_extracts_text_from_image():
    engine = OCREngine()
    if not engine.is_available():
        pytest.skip("No OCR engine available")
    img = Image.new("RGB", (900, 220), "white")
    d = ImageDraw.Draw(img)
    d.text((20, 60), "Non-Disclosure Agreement Template", fill="black")
    d.text((20, 110), "Confidential information protection clause.", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    text = engine.perform_ocr_on_image(buf.getvalue())
    assert len(text) > 0
    assert "non" in text.lower()


def test_compute_embedding_returns_float_vector():
    matcher = SemanticMatcher()
    emb = matcher.compute_embedding("Software development contract template.")
    if not emb:
        pytest.skip("No embedding backend available")
    assert isinstance(emb, list)
    assert all(isinstance(x, float) for x in emb)
    assert len(emb) > 0


def test_retrieve_candidates_uses_cached_embeddings():
    comparator = HybridComparator()
    matcher = comparator.semantic_matcher

    pdf_doc = _make_doc("input.pdf", "input.pdf",
                        "Software Development Contract and Service Level Agreement.")
    source_doc = _make_doc(os.path.join("templates", "word1.docx"), "word1.docx",
                           "Software Development Contract and Service Level Agreement Template.")
    other_doc = _make_doc(os.path.join("templates", "word2.docx"), "word2.docx",
                          "Shipping Invoice and Delivery Terms for goods purchased.")

    # Populate cached embeddings at index-time style
    for doc in (pdf_doc, source_doc, other_doc):
        emb = matcher.compute_embedding(doc.full_text)
        if not emb:
            pytest.skip("No embedding backend available")
        doc.embedding_json = json.dumps(emb)

    candidates = comparator.retrieve_candidates(pdf_doc, [other_doc, source_doc], top_k=1)
    assert len(candidates) == 1
    assert candidates[0].filename == "word1.docx"