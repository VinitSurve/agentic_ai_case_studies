"""
PolicyLens (Case Study 2) – Data Models & Intermediate Representation

Defines the structured intermediate representation for extracted PDF pages,
blocks, bounding boxes, tables, OCR regions, and diagnostics.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Sequence


class BlockType(str, Enum):
    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    LIST_ITEM = "list_item"
    HEADER = "header"
    FOOTER = "footer"
    OCR_REGION = "ocr_region"
    METADATA = "metadata"


class ExtractionMethod(str, Enum):
    NATIVE_TEXT = "native_text"
    PDFPLUMBER_TABLE = "pdfplumber_table"
    OCR_PAGE = "ocr_page"
    OCR_REGION = "ocr_region"


@dataclass(frozen=True)
class BoundingBox:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    @property
    def area(self) -> float:
        return self.width * self.height

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (round(self.x0, 2), round(self.y0, 2), round(self.x1, 2), round(self.y1, 2))

    def overlaps(self, other: "BoundingBox", threshold: float = 0.3) -> bool:
        """Determines if this bounding box overlaps another box beyond an area fraction threshold."""
        ix0 = max(self.x0, other.x0)
        iy0 = max(self.y0, other.y0)
        ix1 = min(self.x1, other.x1)
        iy1 = min(self.y1, other.y1)
        if ix1 <= ix0 or iy1 <= iy0:
            return False
        inter_area = (ix1 - ix0) * (iy1 - iy0)
        smaller_area = min(self.area, other.area)
        if smaller_area <= 0:
            return False
        return (inter_area / smaller_area) >= threshold

    def contains(self, other: "BoundingBox", tolerance: float = 2.0) -> bool:
        """Checks if this bounding box contains the other box within tolerance."""
        return (
            self.x0 - tolerance <= other.x0
            and self.y0 - tolerance <= other.y0
            and self.x1 + tolerance >= other.x1
            and self.y1 + tolerance >= other.y1
        )


@dataclass
class ParsedBlock:
    document_id: str
    page_number: int  # 1-indexed
    block_id: str  # Unique deterministic identifier e.g. "doc_p1_b0"
    block_type: str  # BlockType enum value or string
    text: str
    bounding_box: tuple[float, float, float, float]  # (x0, y0, x1, y1)
    reading_order: int  # 0-indexed sequence on the page
    extraction_method: str  # ExtractionMethod enum value or string
    confidence: float | None = 1.0  # 1.0 for native, 0.0-1.0 for OCR
    table_data: list[list[str]] | None = None  # 2D cell text grid if table
    table_markdown: str | None = None  # Markdown table string if table
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ParsedBlock":
        bbox = data.get("bounding_box")
        if isinstance(bbox, list):
            data["bounding_box"] = tuple(bbox)
        return cls(**data)


@dataclass
class PageDiagnostics:
    document_id: str
    page_number: int
    width: float
    height: float
    is_scanned: bool
    native_char_count: int
    image_count: int
    image_coverage_ratio: float
    ocr_applied: bool
    ocr_trigger_reason: str | None
    ocr_mean_confidence: float | None
    layout_type: str  # "single_column", "two_column", "mixed"
    tables_detected: int
    blocks_count: int
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DocumentDiagnostics:
    document_id: str
    total_pages: int
    ocr_page_count: int = 0
    ocr_region_count: int = 0
    table_count: int = 0
    total_blocks: int = 0
    page_diagnostics: list[PageDiagnostics] = field(default_factory=list)
    parsing_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "total_pages": self.total_pages,
            "ocr_page_count": self.ocr_page_count,
            "ocr_region_count": self.ocr_region_count,
            "table_count": self.table_count,
            "total_blocks": self.total_blocks,
            "page_diagnostics": [p.to_dict() for p in self.page_diagnostics],
            "parsing_errors": self.parsing_errors,
        }


@dataclass
class ParsedDocument:
    document_id: str
    total_pages: int
    blocks: list[ParsedBlock]
    diagnostics: DocumentDiagnostics
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "total_pages": self.total_pages,
            "blocks": [b.to_dict() for b in self.blocks],
            "diagnostics": self.diagnostics.to_dict(),
            "metadata": self.metadata,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def get_page_blocks(self, page_number: int) -> list[ParsedBlock]:
        """Returns all blocks for a given 1-indexed page number sorted by reading order."""
        return sorted(
            [b for b in self.blocks if b.page_number == page_number],
            key=lambda b: b.reading_order,
        )

    def get_tables(self) -> list[ParsedBlock]:
        """Returns all table blocks across the document."""
        return [b for b in self.blocks if b.block_type == BlockType.TABLE]

