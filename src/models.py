from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set

@dataclass
class TableData:
    rows: int
    cols: int
    headers: List[str] = field(default_factory=list)
    cell_text: List[List[str]] = field(default_factory=list)
    flat_text: str = ""

@dataclass
class PageData:
    page_num: int
    text: str = ""
    headings: List[str] = field(default_factory=list)
    tables: List[TableData] = field(default_factory=list)
    is_scanned: bool = False

@dataclass
class DocumentFeatures:
    filepath: str
    filename: str
    folder_name: str
    file_size: int
    last_modified: float
    file_hash: str
    full_text: str = ""
    headings: List[str] = field(default_factory=list)
    paragraphs: List[str] = field(default_factory=list)
    tables: List[TableData] = field(default_factory=list)
    lists: List[str] = field(default_factory=list)
    headers_footers: List[str] = field(default_factory=list)
    keywords: Set[str] = field(default_factory=set)
    page_count: int = 1
    section_count: int = 1
    pages: List[PageData] = field(default_factory=list)
    is_scanned_pdf: bool = False
    embedding_json: Optional[str] = None
    fingerprint: str = ""

@dataclass
class StageReport:
    """Report of a single comparison stage for a candidate document."""
    stage: str
    score: float
    passed: bool
    detail: str = ""
    effect: str = ""  # e.g. "None" | "Reduced confidence" | "Candidate rejected"

@dataclass
class MatchResult:
    word_file_name: str
    file_path: str
    folder_name: str
    overall_score: float  # 0.0 to 100.0
    confidence_score: float  # 0.0 to 100.0
    component_scores: Dict[str, float] = field(default_factory=dict)
    matching_pages: List[int] = field(default_factory=list)
    matching_sections: List[str] = field(default_factory=list)
    last_modified_date: str = ""
    file_size_str: str = ""
    match_category: str = "Standard Match"
    content_score: float = 0.0
    structure_score: float = 0.0
    semantic_score: float = 0.0
    table_score: float = 0.0
    header_footer_score: float = 0.0
    selection_reason: str = ""
    rejected: bool = False
    rejected_reason: str = ""
    verified_source: bool = False
    text_coverage: float = 0.0
    front_coverage: float = 0.0
    match_basis: str = ""
    stage_reports: List[StageReport] = field(default_factory=list)
    debug_stages: List[Dict[str, Any]] = field(default_factory=list)

