"""
PolicyLens (Case Study 2) – Layout Analyzer Module

Analyzes page geometry, detects single-column vs two-column layouts,
identifies full-width blocks, and reconstructs deterministic reading order.
"""

from __future__ import annotations

import logging
import re
from typing import Sequence

from CS2_PolicyLens.src.config import config
from CS2_PolicyLens.src.models import (
    BlockType,
    BoundingBox,
    ParsedBlock,
)

logger = logging.getLogger("PolicyLens.LayoutAnalyzer")


class LayoutAnalyzer:
    def __init__(
        self,
        full_width_ratio: float | None = None,
        column_left_max_x: float | None = None,
        column_right_min_x: float | None = None,
    ):
        self.full_width_ratio = (
            full_width_ratio if full_width_ratio is not None else config.FULL_WIDTH_RATIO
        )
        self.column_left_max_x = (
            column_left_max_x if column_left_max_x is not None else config.COLUMN_LEFT_MAX_X
        )
        self.column_right_min_x = (
            column_right_min_x if column_right_min_x is not None else config.COLUMN_RIGHT_MIN_X
        )

    def classify_page_layout(
        self, blocks: list[ParsedBlock], page_width: float, page_height: float
    ) -> str:
        """
        Determines if a page is 'single_column' or 'two_column'.
        
        Requires substantive content on both left and right sides that are not full-width.
        """
        if not blocks or page_width <= 0:
            return "single_column"

        left_count = 0
        right_count = 0

        for b in blocks:
            # Skip headers, footers, and full-width tables
            if b.block_type in (BlockType.HEADER, BlockType.FOOTER):
                continue

            x0, y0, x1, y1 = b.bounding_box
            width = x1 - x0
            if (width / page_width) >= self.full_width_ratio:
                continue

            if x1 <= (page_width * self.column_left_max_x) and x0 < (page_width * 0.5):
                left_count += 1
            elif x0 >= (page_width * self.column_right_min_x):
                right_count += 1

        if left_count >= 2 and right_count >= 2:
            return "two_column"
        return "single_column"

    def reconstruct_reading_order(
        self, blocks: list[ParsedBlock], page_width: float, page_height: float
    ) -> tuple[list[ParsedBlock], str]:
        """
        Reconstructs reading order across single-column and two-column layouts.
        
        For two-column pages:
        Uses horizontal band decomposition where full-width blocks (titles, wide tables,
        section dividers) split the page vertically. Inside each two-column band,
        left-column blocks are read top-to-bottom, followed by right-column blocks top-to-bottom.
        """
        if not blocks:
            return [], "single_column"

        layout_type = self.classify_page_layout(blocks, page_width, page_height)

        if layout_type == "single_column":
            ordered = self._order_single_column(blocks)
        else:
            ordered = self._order_two_column(blocks, page_width, page_height)

        # Assign normalized reading_order index 0..N-1
        for idx, block in enumerate(ordered):
            block.reading_order = idx

        return ordered, layout_type

    def _order_single_column(self, blocks: list[ParsedBlock]) -> list[ParsedBlock]:
        """Orders single column blocks top-to-bottom with a 4pt baseline snap tolerance."""
        # Baseline snap: group items whose y0 is within 4 points and order left-to-right
        def sort_key(b: ParsedBlock) -> tuple[float, float]:
            snap_y = round(b.bounding_box[1] / 4.0) * 4.0
            return (snap_y, b.bounding_box[0])

        return sorted(blocks, key=sort_key)

    def _order_two_column(
        self, blocks: list[ParsedBlock], page_width: float, page_height: float
    ) -> list[ParsedBlock]:
        """
        Decomposes two-column pages into horizontal bands segmented by full-width blocks.
        """
        full_width_blocks: list[ParsedBlock] = []
        column_blocks: list[ParsedBlock] = []

        for b in blocks:
            x0, y0, x1, y1 = b.bounding_box
            width = x1 - x0
            is_full = (width / page_width) >= self.full_width_ratio
            # Also catch blocks that straddle the column divider substantially
            is_spanning = (x0 < (page_width * 0.40)) and (x1 > (page_width * 0.60))

            if is_full or is_spanning or (b.block_type in (BlockType.HEADER, BlockType.FOOTER) and width >= page_width * 0.50):
                full_width_blocks.append(b)
            else:
                column_blocks.append(b)

        # Sort full width blocks strictly top-to-bottom
        full_width_blocks.sort(key=lambda b: b.bounding_box[1])

        # If no full-width blocks, order entire page as single two-column band
        if not full_width_blocks:
            return self._order_column_band(column_blocks, page_width)

        ordered_result: list[ParsedBlock] = []
        current_y = 0.0

        for fw_block in full_width_blocks:
            fw_y0 = fw_block.bounding_box[1]
            fw_y1 = fw_block.bounding_box[3]

            # Gather column blocks strictly above this full-width block
            band_blocks = [
                b for b in column_blocks
                if current_y <= b.bounding_box[1] < fw_y0
            ]
            if band_blocks:
                ordered_result.extend(self._order_column_band(band_blocks, page_width))

            ordered_result.append(fw_block)
            current_y = max(current_y, fw_y1)

        # Process any remaining column blocks below the last full-width block
        remaining_blocks = [
            b for b in column_blocks
            if b.bounding_box[1] >= current_y
        ]
        if remaining_blocks:
            ordered_result.extend(self._order_column_band(remaining_blocks, page_width))

        # Include any column blocks that may have been missed due to overlapping boundaries
        included_ids = {b.block_id for b in ordered_result}
        missed = [b for b in column_blocks if b.block_id not in included_ids]
        if missed:
            ordered_result.extend(self._order_column_band(missed, page_width))

        return ordered_result

    def _order_column_band(
        self, band_blocks: list[ParsedBlock], page_width: float
    ) -> list[ParsedBlock]:
        """Within a horizontal band, reads all left-column blocks, then all right-column blocks."""
        left_blocks: list[ParsedBlock] = []
        right_blocks: list[ParsedBlock] = []

        for b in band_blocks:
            x0, y0, x1, y1 = b.bounding_box
            mid_x = (x0 + x1) / 2.0
            if mid_x < (page_width * 0.5):
                left_blocks.append(b)
            else:
                right_blocks.append(b)

        left_ordered = self._order_single_column(left_blocks)
        right_ordered = self._order_single_column(right_blocks)
        return left_ordered + right_ordered

    def classify_block_type(
        self,
        text: str,
        bbox: tuple[float, float, float, float],
        font_size: float,
        is_bold: bool,
        median_font_size: float,
        page_height: float,
        page_number: int,
        is_first_block: bool,
        page_width: float = 595.0,
    ) -> str:
        """
        Classifies block semantic type (title, heading, paragraph, list_item, header, footer).
        """
        x0, y0, x1, y1 = bbox
        width = x1 - x0
        stripped = text.strip()

        # Header / Footer geometric detection
        if y1 < (page_height * 0.08) and len(stripped.split()) <= 12:
            return BlockType.HEADER

        if y0 > (page_height * 0.92) and len(stripped.split()) <= 10:
            return BlockType.FOOTER

        # Document Title detection on Page 1 (must span substantially across page width)
        is_wide = (width / max(1.0, page_width)) >= 0.45
        if page_number == 1 and (is_first_block or y0 < page_height * 0.25):
            if is_wide and ((font_size >= median_font_size * 1.25) or (is_bold and font_size > median_font_size)):
                return BlockType.TITLE

        # Heading detection via typography or regulatory numbering pattern
        words = stripped.split()
        if len(words) <= 15:
            # Regulatory clause patterns
            heading_pattern = r"^(CHAPTER\s+[IVXLCDM\d]+|SECTION\s+\d+|PART\s+[A-Z]|\d+\.\s+[A-Z]|\([a-z\d]+\)\s+[A-Z]|Master Direction|Notification|Guidelines|Circular)"
            if re.match(heading_pattern, stripped, re.IGNORECASE):
                return BlockType.HEADING

            if (font_size >= median_font_size * 1.15) or (is_bold and font_size >= median_font_size):
                return BlockType.HEADING

            if stripped.isupper() and len(words) <= 8 and len(stripped) > 4:
                return BlockType.HEADING

        # List item / sub-clause pattern
        if re.match(r"^(\d+\.|\([a-z\d]+\)|•|\-|\*)\s+", stripped):
            return BlockType.LIST_ITEM

        return BlockType.PARAGRAPH
