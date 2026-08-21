import os
import tempfile
import pytest
from src.database import IndexDatabase
from src.models import DocumentFeatures, TableData, PageData

def test_database_crud():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = IndexDatabase(db_path=db_path)

        doc = DocumentFeatures(
            filepath=os.path.join(tmpdir, "test.docx"),
            filename="test.docx",
            folder_name="templates",
            file_size=1024,
            last_modified=1700000000.0,
            file_hash="dummyhash123",
            full_text="This is a test invoice document template.",
            headings=["Invoice Template", "Customer Details"],
            paragraphs=["This is paragraph 1.", "Payment due date is 30 days."],
            tables=[TableData(rows=2, cols=2, headers=["Item", "Price"], cell_text=[["Widget", "$100"]], flat_text="Widget $100")],
            lists=["- Item 1", "- Item 2"],
            keywords={"invoice", "payment", "widget"},
            page_count=1,
            pages=[PageData(page_num=1, text="This is a test invoice document template.", headings=["Invoice Template"])]
        )

        # Save document
        db.save_document(doc)

        # Up to date check
        assert db.is_file_up_to_date(doc.filepath, 1700000000.0, "dummyhash123") is True
        assert db.is_file_up_to_date(doc.filepath, 1700000000.0, "wronghash") is False

        # Get all documents
        all_docs = db.get_all_documents()
        assert len(all_docs) == 1
        retrieved = all_docs[0]
        assert retrieved.filename == "test.docx"
        assert retrieved.headings == ["Invoice Template", "Customer Details"]
        assert len(retrieved.tables) == 1
        assert retrieved.tables[0].headers == ["Item", "Price"]

        # Remove document
        db.remove_document(doc.filepath)
        assert len(db.get_all_documents()) == 0
