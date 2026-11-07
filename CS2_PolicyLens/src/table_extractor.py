"""
PolicyLens (Case Study 2) – Table Extractor Module

Extracts structured tables from PDF pages using pdfplumber, validates cell density,
generates Markdown table representations, and preserves tabular schema.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

import pdfplumber

from CS2_PolicyLens.src.config import config
from CS2_PolicyLens.src.models import (
    BlockType,
    BoundingBox,
    ExtractionMethod,
    ParsedBlock,
)

logger = logging.getLogger("PolicyLens.TableExtractor")


class TableExtractor:
    def __init__(self, max_empty_cell_ratio: float | None = None):
        self.max_empty_cell_ratio = (
            max_empty_cell_ratio
            if max_empty_cell_ratio is not None
            else config.TABLE_MAX_EMPTY_CELL_RATIO
        )

    def extract_page_tables(
        self,
        plumber_page: pdfplumber.page.Page,
        document_id: str,
        page_number: int,
    ) -> list[ParsedBlock]:
        """
        Extracts structured tables from a single pdfplumber page.
        Returns a list of ParsedBlock objects of type BlockType.TABLE.
        """
        table_blocks: list[ParsedBlock] = []

        try:
            found_tables = plumber_page.find_tables()
        except Exception as e:
            logger.warning(f"[{document_id}:p{page_number}] pdfplumber find_tables failed: {e}")
            return []

        for idx, table_obj in enumerate(found_tables):
            try:
                raw_data = table_obj.extract()
            except Exception as e:
                logger.debug(f"[{document_id}:p{page_number}] Table extraction failed on index {idx}: {e}")
                continue

            if not raw_data or len(raw_data) < 2:
                continue

            # Clean and sanitize cell text
            cleaned_grid: list[list[str]] = []
            total_cells = 0
            empty_cells = 0

            for row in raw_data:
                cleaned_row: list[str] = []
                for cell in row:
                    total_cells += 1
                    if cell is None or not str(cell).strip():
                        empty_cells += 1
                        cleaned_row.append("")
                    else:
                        # Normalize cell text: replace line breaks with spaces and escape pipe chars
                        normalized_cell = " ".join(str(cell).split())
                        normalized_cell = normalized_cell.replace("|", "\\|")
                        cleaned_row.append(normalized_cell)
                cleaned_grid.append(cleaned_row)

            # Check column count
            max_cols = max(len(r) for r in cleaned_grid) if cleaned_grid else 0
            if max_cols < 2:
                continue

            # Standardize row lengths to max_cols
            for row in cleaned_grid:
                if len(row) < max_cols:
                    row.extend([""] * (max_cols - len(row)))

            # Validate empty cell ratio
            empty_ratio = (empty_cells / max(1, total_cells))
            if empty_ratio > self.max_empty_cell_ratio:
                logger.debug(
                    f"[{document_id}:p{page_number}] Rejected table {idx}: empty ratio {empty_ratio:.2f} > {self.max_empty_cell_ratio:.2f}"
                )
                continue

            # Format Markdown table
            markdown_table = self._format_markdown_table(cleaned_grid)
            if not markdown_table:
                continue

            # Bounding box from table_obj: (x0, top, x1, bottom) -> (x0, y0, x1, y1)
            bbox = (
                round(float(table_obj.bbox[0]), 2),
                round(float(table_obj.bbox[1]), 2),
                round(float(table_obj.bbox[2]), 2),
                round(float(table_obj.bbox[3]), 2),
            )

            block_id = f"{document_id}_p{page_number}_tbl{idx}"
            table_blocks.append(
                ParsedBlock(
                    document_id=document_id,
                    page_number=page_number,
                    block_id=block_id,
                    block_type=BlockType.TABLE,
                    text=markdown_table,
                    bounding_box=bbox,
                    reading_order=0,  # Ordered in LayoutAnalyzer
                    extraction_method=ExtractionMethod.PDFPLUMBER_TABLE,
                    confidence=1.0,
                    table_data=cleaned_grid,
                    table_markdown=markdown_table,
                    metadata={
                        "row_count": len(cleaned_grid),
                        "col_count": max_cols,
                        "empty_cell_ratio": round(empty_ratio, 4),
                    },
                )
            )

        return table_blocks

    def _format_markdown_table(self, grid: list[list[str]]) -> str | None:
        """Converts a 2D grid into a clean, compliant Markdown table string."""
        if not grid or len(grid) < 2:
            return None

        header = grid[0]
        # Ensure header cells are not all empty
        if not any(header):
            # Fallback header names if first row is completely blank
            header = [f"Col {i+1}" for i in range(len(header))]

        lines: list[str] = []
        lines.append("| " + " | ".join(header) + " |")
        lines.append("| " + " | ".join(["---"] * len(header)) + " |")

        for row in grid[1:]:
            lines.append("| " + " | ".join(row) + " |")

        return "\n".join(lines)

