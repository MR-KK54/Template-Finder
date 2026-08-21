import pytest
from src.models import DocumentFeatures, TableData, PageData
from src.matcher.text_matcher import TextMatcher
from src.matcher.structural_matcher import StructuralMatcher
from src.matcher.hybrid_comparator import HybridComparator

def test_text_matcher():
    matcher = TextMatcher()
    t1 = "Non-Disclosure Agreement and Confidentiality Terms"
    t2 = "Non Disclosure Agreement Confidentiality Terms"
    score = matcher.compute_text_similarity(t1, t2)
    assert score > 80.0

def test_structural_matcher():
    matcher = StructuralMatcher()
    headings1 = ["Introduction", "Scope of Work", "Payment Terms"]
    headings2 = ["Introduction", "Scope of Work", "Payment Terms and Invoicing"]
    h_score = matcher.compute_heading_similarity(headings1, headings2)
    assert h_score > 80.0

    tables1 = [TableData(rows=3, cols=3, headers=["ID", "Name", "Cost"], cell_text=[], flat_text="ID Name Cost")]
    tables2 = [TableData(rows=3, cols=3, headers=["ID", "Name", "Price"], cell_text=[], flat_text="ID Name Price")]
    tbl_score = matcher.compute_table_similarity(tables1, tables2)
    assert tbl_score > 70.0

def test_hybrid_comparator():
    comparator = HybridComparator()

    doc1 = DocumentFeatures(
        filepath="pdf1.pdf", filename="pdf1.pdf", folder_name="input", file_size=5000,
        last_modified=1700000000.0, file_hash="hash1",
        full_text="Software Development Contract and Service Level Agreement.",
        headings=["Software Development Contract", "Service Level Agreement"],
        paragraphs=["Developer agrees to provide software services."],
        tables=[TableData(rows=2, cols=2, headers=["Service", "Fee"], flat_text="Service Fee")],
        keywords={"software", "contract", "service", "developer"},
        page_count=2,
        pages=[PageData(page_num=1, text="Software Development Contract", headings=["Software Development Contract"])]
    )

    doc2 = DocumentFeatures(
        filepath="word1.docx", filename="word1.docx", folder_name="templates", file_size=5500,
        last_modified=1700000000.0, file_hash="hash2",
        full_text="Software Development Contract and Service Level Agreement Template.",
        headings=["Software Development Contract", "Service Level Agreement"],
        paragraphs=["Developer agrees to provide software services."],
        tables=[TableData(rows=2, cols=2, headers=["Service", "Fee"], flat_text="Service Fee")],
        keywords={"software", "contract", "service", "template"},
        page_count=2,
        pages=[PageData(page_num=1, text="Software Development Contract", headings=["Software Development Contract"])]
    )

    match_res = comparator.compare(doc1, doc2)
    assert match_res.overall_score >= 70.0
    assert match_res.confidence_score > 60.0
    assert "Software Development Contract" in match_res.matching_sections
