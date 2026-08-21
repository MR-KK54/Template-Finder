import os
import tempfile
import pytest
from src.database import IndexDatabase
from src.models import DocumentFeatures, PageData
from src.matcher.hybrid_comparator import HybridComparator
from src.utils.file_utils import canonical_path


def _make_doc(filepath: str, filename: str, full_text: str, headings: list,
              keywords: set, file_hash: str) -> DocumentFeatures:
    return DocumentFeatures(
        filepath=filepath,
        filename=filename,
        folder_name=os.path.basename(os.path.dirname(filepath)),
        file_size=5000,
        last_modified=1700000000.0,
        file_hash=file_hash,
        full_text=full_text,
        headings=headings,
        paragraphs=[full_text],
        keywords=set(keywords),
        page_count=1,
        pages=[PageData(page_num=1, text=full_text, headings=headings)]
    )


def test_canonical_path_strips_long_prefix_and_normalizes():
    p = r"\\?\D:\Some\Folder\File.docx"
    assert canonical_path(p) == os.path.normcase(r"D:\Some\Folder\File.docx")


def test_prune_index_removes_stale_entries():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = IndexDatabase(db_path=db_path)

        doc_a = _make_doc(os.path.join(tmpdir, "a.docx"), "a.docx", "text a", ["H1"], {"k1"}, "hash-a")
        doc_b = _make_doc(os.path.join(tmpdir, "b.docx"), "b.docx", "text b", ["H1"], {"k1"}, "hash-b")
        db.save_document(doc_a)
        db.save_document(doc_b)
        assert len(db.get_all_documents()) == 2

        db.prune_index({canonical_path(os.path.join(tmpdir, "a.docx"))})
        docs = db.get_all_documents()
        assert len(docs) == 1
        assert docs[0].filename == "a.docx"


def test_get_all_documents_deduplicates_by_hash():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = IndexDatabase(db_path=db_path)

        p1 = os.path.join(tmpdir, "a.docx")
        sub = os.path.join(tmpdir, "sub")
        os.makedirs(sub, exist_ok=True)
        p2 = os.path.join(sub, "a.docx")

        db.save_document(_make_doc(p1, "a.docx", "same content", ["H1"], {"k1"}, "same-hash"))
        db.save_document(_make_doc(p2, "a.docx", "same content", ["H1"], {"k1"}, "same-hash"))

        docs = db.get_all_documents()
        assert len(docs) == 1
        assert docs[0].filepath == canonical_path(p1)


def test_retrieve_candidates_returns_top_k_and_ranks_source_first():
    comparator = HybridComparator()
    pdf_doc = _make_doc(
        "input.pdf", "input.pdf",
        "Software Development Contract and Service Level Agreement.",
        ["Software Development Contract"], {"software", "contract", "service"}, "hash-pdf"
    )
    source_doc = _make_doc(
        os.path.join("templates", "word1.docx"), "word1.docx",
        "Software Development Contract and Service Level Agreement Template.",
        ["Software Development Contract", "Service Level Agreement"],
        {"software", "contract", "service", "template"}, "hash-1"
    )
    other_doc = _make_doc(
        os.path.join("templates", "word2.docx"), "word2.docx",
        "Shipping Invoice and Delivery Terms for goods purchased.",
        ["Shipping Invoice"], {"shipping", "invoice", "delivery"}, "hash-2"
    )

    candidates = comparator.retrieve_candidates(pdf_doc, [other_doc, source_doc], top_k=1)
    assert len(candidates) == 1
    assert candidates[0].filename == "word1.docx"


def test_compare_batch_ranks_original_source_first_without_duplicates():
    comparator = HybridComparator()
    pdf_doc = _make_doc(
        "input.pdf", "input.pdf",
        "Software Development Contract and Service Level Agreement.",
        ["Software Development Contract"], {"software", "contract", "service"}, "hash-pdf"
    )
    source_doc = _make_doc(
        os.path.join("templates", "word1.docx"), "word1.docx",
        "Software Development Contract and Service Level Agreement Template.",
        ["Software Development Contract", "Service Level Agreement"],
        {"software", "contract", "service", "template"}, "hash-1"
    )
    unrelated_doc = _make_doc(
        os.path.join("templates", "word2.docx"), "word2.docx",
        "Shipping Invoice and Delivery Terms for goods purchased.",
        ["Shipping Invoice"], {"shipping", "invoice", "delivery"}, "hash-2"
    )

    results = comparator.compare_batch(pdf_doc, [unrelated_doc, source_doc], top_k=2)
    assert len(results) == 2
    assert results[0].word_file_name == "word1.docx"
    names = [r.word_file_name for r in results]
    assert len(names) == len(set(names))


def test_compare_batch_exhaustive_compares_every_document():
    """compare_all=True with a large max_candidates must deep-compare every document."""
    comparator = HybridComparator()
    pdf_doc = _make_doc(
        "input.pdf", "input.pdf",
        "Software Development Contract and Service Level Agreement.",
        ["Software Development Contract"], {"software", "contract", "service"}, "hash-pdf"
    )
    docs = []
    for i in range(8):
        docs.append(_make_doc(
            os.path.join("templates", f"doc{i}.docx"), f"doc{i}.docx",
            f"Software Development Contract and Service Level Agreement {i}.",
            ["Software Development Contract"], {"software", "contract", "service"}, f"hash-{i}"
        ))

    results = comparator.compare_batch(pdf_doc, docs, max_candidates=500)
    # Every one of the 8 documents was compared and returned (accepted or rejected).
    assert len(results) == 8
    names = {r.word_file_name for r in results}
    assert names == {f"doc{i}.docx" for i in range(8)}


def test_compare_batch_default_uses_top_5_candidates():
    """The default candidate pool is the Top-5 retrieved documents."""
    comparator = HybridComparator()
    pdf_doc = _make_doc(
        "input.pdf", "input.pdf",
        "Software Development Contract and Service Level Agreement.",
        ["Software Development Contract"], {"software", "contract", "service"}, "hash-pdf"
    )
    docs = []
    for i in range(10):
        docs.append(_make_doc(
            os.path.join("templates", f"doc{i}.docx"), f"doc{i}.docx",
            f"Software Development Contract and Service Level Agreement {i}.",
            ["Software Development Contract"], {"software", "contract", "service"}, f"hash-{i}"
        ))

    results = comparator.compare_batch(pdf_doc, docs)
    assert len(results) == 5


def test_compare_batch_finds_exact_source_within_top_5():
    """The exact original source document must be found in the default Top-5 pool."""
    comparator = HybridComparator()
    pdf_doc = _make_doc(
        "input.pdf", "input.pdf",
        "Software Development Contract and Service Level Agreement.",
        ["Software Development Contract"], {"software", "contract", "service"}, "hash-pdf"
    )
    source_doc = _make_doc(
        os.path.join("templates", "word1.docx"), "word1.docx",
        "Software Development Contract and Service Level Agreement Template.",
        ["Software Development Contract", "Service Level Agreement"],
        {"software", "contract", "service", "template"}, "hash-1"
    )
    # 20 filler documents that are clearly unrelated to the PDF
    docs = [source_doc]
    for i in range(20):
        docs.append(_make_doc(
            os.path.join("templates", f"filler{i}.docx"), f"filler{i}.docx",
            f"Shipping Invoice and Delivery Terms for goods purchased {i}.",
            ["Shipping Invoice"], {"shipping", "invoice", "delivery"}, f"hash-f{i}"
        ))

    results = comparator.compare_batch(pdf_doc, docs)
    assert len(results) == 5
    top = [r for r in results if not r.rejected]
    assert top and top[0].word_file_name == "word1.docx"


def test_compare_batch_progress_callback_called():
    comparator = HybridComparator()
    pdf_doc = _make_doc(
        "input.pdf", "input.pdf",
        "Software Development Contract and Service Level Agreement.",
        ["Software Development Contract"], {"software", "contract", "service"}, "hash-pdf"
    )
    docs = [_make_doc(
        os.path.join("templates", f"doc{i}.docx"), f"doc{i}.docx",
        f"Software Development Contract and Service Level Agreement {i}.",
        ["Software Development Contract"], {"software", "contract", "service"}, f"hash-{i}"
    ) for i in range(4)]

    progress_calls = []
    comparator.compare_batch(
        pdf_doc, docs,
        progress_callback=lambda done, total, name: progress_calls.append((done, total)),
    )
    assert len(progress_calls) == 4
    assert progress_calls[-1][0] == progress_calls[-1][1] == 4