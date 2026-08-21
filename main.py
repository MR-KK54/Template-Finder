import sys
import os
import argparse
from pathlib import Path

# Add workspace directory to python sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.utils.logger import get_logger

logger = get_logger("main")

def run_gui():
    """Launches the PySide6 Desktop GUI Application."""
    from PySide6.QtWidgets import QApplication
    from src.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("PDF to Word Template Finder")
    app.setOrganizationName("Antigravity")

    window = MainWindow()
    window.show()

    logger.info("PDF to Word Template Finder GUI started.")
    sys.exit(app.exec())

def run_cli(pdf_path: str, folder_path: str, threshold: float, front_page_only: bool = False,
            fast: bool = False, max_candidates: int = 5):
    """Runs template search via CLI mode."""
    logger.info(f"Running CLI Template Search: PDF={pdf_path}, Folder={folder_path}, Threshold={threshold}%"
                f"{', Front-Page-Only' if front_page_only else ''}"
                f"{', Fast(Top-20)' if fast else ', Top-' + str(max_candidates) + ' candidates'}")
    from src.indexer.index_manager import IndexManager
    from src.extractors.pdf_extractor import PDFExtractor
    from src.matcher.hybrid_comparator import HybridComparator

    index_mgr = IndexManager()
    index_mgr.index_directory(folder_path)

    pdf_extractor = PDFExtractor()
    pdf_doc = pdf_extractor.extract(pdf_path)

    word_docs = index_mgr.db.get_all_documents()
    comparator = HybridComparator()

    all_results = comparator.compare_batch(
        pdf_doc, word_docs, compare_all=not fast, max_candidates=max_candidates
    )
    results = [r for r in all_results if not r.rejected and (r.overall_score >= threshold or r.verified_source)]
    if front_page_only:
        results = [r for r in results if r.verified_source and r.match_basis in ("front page", "both")]
    results.sort(key=lambda x: x.overall_score, reverse=True)

    print("\n" + "=" * 100)
    print(f"MATCH RESULTS ({len(results)} matches >= {threshold}%):")
    print("=" * 100)
    for r in results:
        marker = f" [VERIFIED SOURCE - {r.match_basis.upper()}]" if r.verified_source else ""
        print(f"Match: {r.overall_score:.1f}% | Confidence: {r.confidence_score:.1f}% | File: {r.word_file_name}{marker}")
        print(f"   Path: {r.file_path}")
        print(f"   Content: {r.content_score:.1f}% | Structure: {r.structure_score:.1f}% | "
              f"Semantic: {r.semantic_score:.1f}% | Tables: {r.table_score:.1f}% | Header/Footer: {r.header_footer_score:.1f}%")
        print(f"   Coverage: front page {r.front_coverage:.1f}% | full document {r.text_coverage:.1f}%")
        print(f"   Why selected: {r.selection_reason}")
        if r.matching_sections:
            print(f"   Matching Sections: {', '.join(r.matching_sections)}")
        print("-" * 100)

    rejected = [r for r in all_results if r.rejected]
    if rejected:
        print(f"\nDEBUG - Rejected candidates ({len(rejected)}):")
        for r in rejected:
            print(f"   - {r.word_file_name}: {r.rejected_reason}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PDF to Word Template Finder")
    parser.add_argument("--cli", action="store_true", help="Run in Command Line Interface mode")
    parser.add_argument("--pdf", type=str, help="Path to input PDF file (CLI mode)")
    parser.add_argument("--folder", type=str, help="Path to Word templates directory (CLI mode)")
    parser.add_argument("--threshold", type=float, default=100.0, help="Similarity threshold percentage (default: 100.0)")
    parser.add_argument("--front-page", action="store_true", help="Show only matches verified by the PDF's front page")
    parser.add_argument("--fast", action="store_true", help="Compare only the Top-20 retrieved candidates (faster, less exhaustive)")
    parser.add_argument("--max-candidates", type=int, default=5, help="Max documents to deeply compare (default: 5)")

    args = parser.parse_args()

    if args.cli and args.pdf and args.folder:
        run_cli(args.pdf, args.folder, args.threshold, front_page_only=args.front_page,
                fast=args.fast, max_candidates=args.max_candidates)
    else:
        run_gui()
