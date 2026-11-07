"""
PolicyLens (Case Study 2) – Unit Tests for PDF Parser & Layout Analysis Engine

Uses synthetic, programmatic PDF fixtures to thoroughly test:
1. Single-column page reading order, headings, and paragraphs.
2. Two-column layout detection and band-based reading order reconstruction.
3. Structured table extraction via pdfplumber and Markdown table formatting.
4. Full-page OCR fallback on scanned textless pages using Tesseract.
5. Hybrid native text with regional OCR extraction on embedded scanned images.
6. Deterministic parsing and structured intermediate representation serialization.
"""

from __future__ import annotations

import io
import shutil
import tempfile
import unittest
from pathlib import Path

import PIL.Image as PILImage
import PIL.ImageDraw as PILDraw
import pymupdf as fitz

from CS2_PolicyLens.src.config import config
from CS2_PolicyLens.src.models import (
    BlockType,
    ExtractionMethod,
    ParsedBlock,
    ParsedDocument,
)
from CS2_PolicyLens.src.pdf_parser import PDFParser


class TestPDFParserFoundation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = Path(tempfile.mkdtemp(prefix="policylens_test_"))
        cls.parser = PDFParser()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # FIXTURE BUILDERS
    # -------------------------------------------------------------------------
    def _create_single_column_pdf(self) -> Path:
        pdf_path = self.temp_dir / "single_column.pdf"
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)  # A4 size

        # 1. Title
        page.insert_textbox(
            fitz.Rect(50, 50, 545, 90),
            "Reserve Bank of India Master Direction 2026",
            fontsize=16,
            fontname="helv",
        )
        # 2. Section Heading
        page.insert_textbox(
            fitz.Rect(50, 110, 545, 140),
            "1. Short Title and Commencement",
            fontsize=13,
            fontname="helv",
        )
        # 3. Paragraph
        page.insert_textbox(
            fitz.Rect(50, 150, 545, 230),
            "These directions shall be called the Reserve Bank of India (Commercial Banks) Directions, 2026. "
            "They shall come into force with effect from July 1, 2026 across all scheduled commercial banks.",
            fontsize=10,
            fontname="helv",
        )
        # 4. List item / clause
        page.insert_textbox(
            fitz.Rect(50, 240, 545, 280),
            "(a) All banking companies licensed under Section 22 of the Banking Regulation Act, 1949.",
            fontsize=10,
            fontname="helv",
        )
        # 5. Running footer at bottom
        page.insert_textbox(
            fitz.Rect(50, 800, 545, 825),
            "Page 1 of 1 - Confidential Regulatory Filing",
            fontsize=8,
            fontname="helv",
        )

        doc.save(str(pdf_path))
        doc.close()
        return pdf_path

    def _create_two_column_pdf(self) -> Path:
        pdf_path = self.temp_dir / "two_column.pdf"
        doc = fitz.open()
        page = doc.new_page(width=600, height=800)

        # Full-width banner title across both columns
        page.insert_textbox(
            fitz.Rect(50, 40, 550, 90),
            "Monetary Policy Review and Macroeconomic Financial Stability Overview",
            fontsize=15,
            fontname="helv",
        )

        # Column 1 (Left: x in 50..270)
        page.insert_textbox(
            fitz.Rect(50, 110, 270, 140),
            "Domestic Economic Momentum",
            fontsize=12,
            fontname="helv",
        )
        page.insert_textbox(
            fitz.Rect(50, 150, 270, 260),
            "The domestic growth trajectory remains supported by resilient urban consumption, "
            "accelerated public capital expenditure, and healthy balance sheets of commercial banks.",
            fontsize=9.5,
            fontname="helv",
        )

        # Column 2 (Right: x in 330..550) - Same vertical position as Left column!
        page.insert_textbox(
            fitz.Rect(330, 110, 550, 140),
            "Global Inflation Outlook",
            fontsize=12,
            fontname="helv",
        )
        page.insert_textbox(
            fitz.Rect(330, 150, 550, 260),
            "Headline inflation across key advanced economies continues its gradual descent toward targets, "
            "though persistent service price pressures and volatile energy markets pose upside risks.",
            fontsize=9.5,
            fontname="helv",
        )

        # Full-width concluding section spanning both columns at bottom
        page.insert_textbox(
            fitz.Rect(50, 300, 550, 360),
            "Summary Conclusion: Prudent regulatory buffers and proactive liquidity management "
            "provide sufficient resilience to absorb external shocks.",
            fontsize=10,
            fontname="helv",
        )

        doc.save(str(pdf_path))
        doc.close()
        return pdf_path

    def _create_table_pdf(self) -> Path:
        pdf_path = self.temp_dir / "table_document.pdf"
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)

        # Introductory paragraph above table
        page.insert_textbox(
            fitz.Rect(50, 40, 545, 80),
            "Annexure II: Minimum Capital Adequacy Ratios and Risk Weight Schedule",
            fontsize=12,
            fontname="helv",
        )

        # Draw Table Grid using lines so pdfplumber detects lines
        # Table bbox: x in [50, 540], y in [100, 220]
        # 4 horizontal lines, 4 vertical lines (3 rows x 3 columns)
        x_coords = [50.0, 210.0, 370.0, 540.0]
        y_coords = [100.0, 140.0, 180.0, 220.0]

        # Horizontal borders
        for y in y_coords:
            page.draw_line(fitz.Point(x_coords[0], y), fitz.Point(x_coords[-1], y), color=(0, 0, 0), width=1)
        # Vertical borders
        for x in x_coords:
            page.draw_line(fitz.Point(x, y_coords[0]), fitz.Point(x, y_coords[-1]), color=(0, 0, 0), width=1)

        # Cell contents
        table_cells = [
            # Row 0: Headers
            ("Asset Category", fitz.Rect(55, 105, 205, 135)),
            ("Risk Weight", fitz.Rect(215, 105, 365, 135)),
            ("Minimum Capital", fitz.Rect(375, 105, 535, 135)),
            # Row 1
            ("Retail Mortgages", fitz.Rect(55, 145, 205, 175)),
            ("35 Percent", fitz.Rect(215, 145, 365, 175)),
            ("9.0 Percent", fitz.Rect(375, 145, 535, 175)),
            # Row 2
            ("Commercial Real Estate", fitz.Rect(55, 185, 205, 215)),
            ("100 Percent", fitz.Rect(215, 185, 365, 215)),
            ("11.5 Percent", fitz.Rect(375, 185, 535, 215)),
        ]
        for text, rect in table_cells:
            page.insert_textbox(rect, text, fontsize=9.5, fontname="helv")

        # Concluding note below table
        page.insert_textbox(
            fitz.Rect(50, 240, 545, 280),
            "Note: The capital charge is calculated in accordance with Basel III standardized guidelines.",
            fontsize=9.5,
            fontname="helv",
        )

        doc.save(str(pdf_path))
        doc.close()
        return pdf_path

    def _create_scanned_pdf(self) -> Path:
        pdf_path = self.temp_dir / "scanned_document.pdf"
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)

        # Create a pure bitmap image with no native text layer
        img = PILImage.new("RGB", (1200, 600), color=(255, 255, 255))
        draw = PILDraw.Draw(img)
        draw.text((80, 80), "MINISTRY OF FINANCE NOTIFICATION", fill=(0, 0, 0))
        draw.text((80, 160), "ORDER NO 2026 FINANCIAL SERVICES APPOINTMENT", fill=(0, 0, 0))
        draw.text((80, 240), "THE PRESIDENT IS PLEASED TO APPOINT THE FOLLOWING MEMBERS", fill=(0, 0, 0))

        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format="PNG")
        img_bytes = img_byte_arr.getvalue()

        # Insert as full-page raster image (0 native text characters in PDF)
        page.insert_image(fitz.Rect(50, 50, 545, 400), stream=img_bytes)

        doc.save(str(pdf_path))
        doc.close()
        return pdf_path

    def _create_hybrid_ocr_region_pdf(self) -> Path:
        pdf_path = self.temp_dir / "hybrid_document.pdf"
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)

        # 1. Native text block
        page.insert_textbox(
            fitz.Rect(50, 50, 545, 120),
            "Department of Financial Services, Ministry of Finance, New Delhi.\n"
            "This regulatory circular is issued under Section 45 of the RBI Act.",
            fontsize=11,
            fontname="helv",
        )

        # 2. Small embedded scanned seal / stamp image
        stamp_img = PILImage.new("RGB", (400, 150), color=(240, 240, 240))
        draw = PILDraw.Draw(stamp_img)
        draw.text((30, 40), "OFFICIAL REGULATORY SEAL", fill=(0, 0, 0))
        draw.text((30, 80), "VERIFIED NEW DELHI 2026", fill=(0, 0, 0))

        stamp_bytes_io = io.BytesIO()
        stamp_img.save(stamp_bytes_io, format="PNG")

        # Insert image in non-overlapping lower area
        page.insert_image(fitz.Rect(50, 160, 250, 260), stream=stamp_bytes_io.getvalue())

        doc.save(str(pdf_path))
        doc.close()
        return pdf_path

    # -------------------------------------------------------------------------
    # TEST CASES
    # -------------------------------------------------------------------------
    def test_single_column_parsing(self):
        """Tests single-column layout extraction, headings, paragraphs, and reading order."""
        pdf_path = self._create_single_column_pdf()
        parsed = self.parser.parse_file(pdf_path, document_id="single_col_test")

        self.assertEqual(parsed.document_id, "single_col_test")
        self.assertEqual(parsed.total_pages, 1)
        self.assertGreater(len(parsed.blocks), 3)

        diag = parsed.diagnostics.page_diagnostics[0]
        self.assertFalse(diag.is_scanned)
        self.assertEqual(diag.layout_type, "single_column")
        self.assertFalse(diag.ocr_applied)

        # Verify reading order monotonicity
        reading_orders = [b.reading_order for b in parsed.blocks]
        self.assertEqual(reading_orders, list(range(len(parsed.blocks))))

        # Verify block type classifications
        block_types = [b.block_type for b in parsed.blocks]
        self.assertIn(BlockType.TITLE, block_types)
        self.assertIn(BlockType.HEADING, block_types)
        self.assertIn(BlockType.PARAGRAPH, block_types)
        self.assertIn(BlockType.FOOTER, block_types)

        # Verify extraction method
        for b in parsed.blocks:
            self.assertEqual(b.extraction_method, ExtractionMethod.NATIVE_TEXT)
            self.assertEqual(b.confidence, 1.0)

    def test_two_column_reading_order_reconstruction(self):
        """
        Tests that two-column pages are correctly detected and reading order traverses
        Top Full-Width Banner -> Left Column -> Right Column -> Bottom Full-Width Banner.
        """
        pdf_path = self._create_two_column_pdf()
        parsed = self.parser.parse_file(pdf_path, document_id="two_col_test")

        diag = parsed.diagnostics.page_diagnostics[0]
        self.assertEqual(diag.layout_type, "two_column")

        # Find specific blocks
        blocks = parsed.blocks
        banner_block = next((b for b in blocks if "Macroeconomic Financial Stability" in b.text), None)
        left_head = next((b for b in blocks if "Domestic Economic Momentum" in b.text), None)
        left_body = next((b for b in blocks if "domestic growth trajectory" in b.text), None)
        right_head = next((b for b in blocks if "Global Inflation Outlook" in b.text), None)
        right_body = next((b for b in blocks if "advanced economies" in b.text), None)
        bottom_block = next((b for b in blocks if "Summary Conclusion" in b.text), None)

        self.assertIsNotNone(banner_block)
        self.assertIsNotNone(left_head)
        self.assertIsNotNone(left_body)
        self.assertIsNotNone(right_head)
        self.assertIsNotNone(right_body)
        self.assertIsNotNone(bottom_block)

        # Assert correct reading order:
        # Banner (Order 0) < Left Column < Right Column < Bottom Banner
        self.assertLess(banner_block.reading_order, left_head.reading_order)
        self.assertLess(left_head.reading_order, left_body.reading_order)
        self.assertLess(left_body.reading_order, right_head.reading_order)
        self.assertLess(right_head.reading_order, right_body.reading_order)
        self.assertLess(right_body.reading_order, bottom_block.reading_order)

    def test_structured_table_extraction(self):
        """Tests structured table detection, schema preservation, and Markdown rendering."""
        pdf_path = self._create_table_pdf()
        parsed = self.parser.parse_file(pdf_path, document_id="table_test")

        tables = parsed.get_tables()
        self.assertGreaterEqual(len(tables), 1, "Expected at least 1 structured table to be detected")

        table_block = tables[0]
        self.assertEqual(table_block.block_type, BlockType.TABLE)
        self.assertEqual(table_block.extraction_method, ExtractionMethod.PDFPLUMBER_TABLE)
        self.assertIsNotNone(table_block.table_data)
        self.assertIsNotNone(table_block.table_markdown)

        # Check table contents
        grid = table_block.table_data
        self.assertGreaterEqual(len(grid), 3)  # At least 3 rows
        header_row = [c.lower() for c in grid[0]]
        self.assertTrue(any("asset" in c for c in header_row))
        self.assertTrue(any("risk" in c for c in header_row))

        # Check Markdown format
        self.assertIn("| Asset Category |", table_block.table_markdown)
        self.assertIn("| Retail Mortgages |", table_block.table_markdown)

        # Check that table text is not duplicated as raw paragraph
        raw_non_table_texts = [b.text for b in parsed.blocks if b.block_type != BlockType.TABLE]
        for t in raw_non_table_texts:
            self.assertNotIn("Commercial Real Estate\n100 Percent", t)

    def test_scanned_page_ocr_fallback(self):
        """Tests full-page OCR fallback on a textless scanned raster page."""
        pdf_path = self._create_scanned_pdf()
        parsed = self.parser.parse_file(pdf_path, document_id="scanned_test")

        diag = parsed.diagnostics.page_diagnostics[0]
        self.assertTrue(diag.is_scanned, "Page should be detected as scanned")
        self.assertTrue(diag.ocr_applied, "OCR should be applied")
        self.assertIn(
            diag.ocr_trigger_reason,
            ("scanned_raster_page", "empty_text_layer", "low_native_chars_with_images"),
        )
        self.assertGreater(diag.ocr_mean_confidence or 0.0, 0.40)

        # Check that OCR extracted the text from the raster image
        full_extracted = " ".join(b.text for b in parsed.blocks).upper()
        self.assertTrue(
            ("MINISTRY" in full_extracted) or ("FINANCE" in full_extracted) or ("NOTIFICATION" in full_extracted),
            f"Expected OCR to extract text from image, got: {full_extracted}",
        )
        self.assertEqual(parsed.blocks[0].extraction_method, ExtractionMethod.OCR_PAGE)

    def test_hybrid_native_with_ocr_region(self):
        """Tests that a page with native text preserves native blocks while OCRing embedded images."""
        pdf_path = self._create_hybrid_ocr_region_pdf()
        parsed = self.parser.parse_file(pdf_path, document_id="hybrid_test")

        # Native text must be preserved
        native_blocks = [b for b in parsed.blocks if b.extraction_method == ExtractionMethod.NATIVE_TEXT]
        self.assertGreaterEqual(len(native_blocks), 1)
        self.assertIn("Department of Financial Services", native_blocks[0].text)

        # Regional OCR block should be extracted for the embedded image stamp
        ocr_regions = [b for b in parsed.blocks if b.extraction_method == ExtractionMethod.OCR_REGION]
        self.assertGreaterEqual(len(ocr_regions), 1, "Expected at least 1 regional OCR block")

        ocr_text = ocr_regions[0].text.upper()
        self.assertTrue(
            ("SEAL" in ocr_text) or ("REGULATORY" in ocr_text) or ("DELHI" in ocr_text),
            f"Expected OCR region text, got: {ocr_text}",
        )
        self.assertEqual(ocr_regions[0].block_type, BlockType.OCR_REGION)

    def test_determinism_and_serialization(self):
        """Tests that two consecutive runs produce byte-for-byte identical intermediate structures."""
        pdf_path = self._create_single_column_pdf()
        run1 = self.parser.parse_file(pdf_path, document_id="det_test")
        run2 = self.parser.parse_file(pdf_path, document_id="det_test")

        self.assertEqual(run1.to_dict(), run2.to_dict())
        self.assertEqual(run1.to_json(), run2.to_json())

        # Test from_dict reconstruction
        block = run1.blocks[0]
        block_dict = block.to_dict()
        reconstructed_block = ParsedBlock.from_dict(block_dict)
        self.assertEqual(block.block_id, reconstructed_block.block_id)
        self.assertEqual(block.bounding_box, reconstructed_block.bounding_box)

    def test_genuinely_blank_page_skips_ocr(self):
        """
        Tests that genuinely blank pages (0 native text, 0 images) do NOT trigger
        full-page OCR fallback, distinguishing them from textless scanned pages.
        """
        pdf_path = self.temp_dir / "blank_page.pdf"
        doc = fitz.open()
        doc.new_page(width=595, height=842)  # Completely blank page
        doc.save(str(pdf_path))
        doc.close()

        parsed = self.parser.parse_file(pdf_path, document_id="blank_test")
        self.assertEqual(parsed.total_pages, 1)
        self.assertEqual(len(parsed.blocks), 0, "Blank page should yield 0 extracted blocks")

        diag = parsed.diagnostics.page_diagnostics[0]
        self.assertFalse(diag.is_scanned, "Genuinely blank page must not be flagged as scanned")
        self.assertFalse(diag.ocr_applied, "OCR must not be executed on a blank page")
        self.assertIsNone(diag.ocr_trigger_reason)
        self.assertEqual(diag.native_char_count, 0)
        self.assertEqual(diag.image_count, 0)
        self.assertIn("Genuinely blank page; OCR bypassed", diag.warnings)

    def test_overlapping_images_coverage_union(self):
        """
        Tests that image coverage ratio uses the exact 2D union area, avoiding
        double-counting overlapping image placements and keeping the ratio bounded <= 1.0.
        """
        from CS2_PolicyLens.src.ocr_engine import OCREngine

        # 1. Direct unit test of rectangle union sweep-line
        r1 = (0.0, 0.0, 100.0, 100.0)  # Area 10,000
        r2 = (50.0, 0.0, 150.0, 100.0)  # Area 10,000, overlaps r1 on (50..100, 0..100)
        # Expected union = 10,000 + 10,000 - 5,000 = 15,000
        union_area = OCREngine.calculate_rectangles_union_area([r1, r2])
        self.assertEqual(union_area, 15000.0)

        # Identical overlapping rectangles
        self.assertEqual(OCREngine.calculate_rectangles_union_area([r1, r1]), 10000.0)

        # 2. End-to-end PDF test with overlapping placed images
        pdf_path = self.temp_dir / "overlapping_images.pdf"
        doc = fitz.open()
        page = doc.new_page(width=600, height=800)  # Page Area = 480,000

        # Create sample test image (300x300 pt)
        img = PILImage.new("RGB", (300, 300), color=(200, 200, 200))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img_bytes = buf.getvalue()

        # Place image 1 at (50, 50, 350, 350) -> Area 90,000
        page.insert_image(fitz.Rect(50, 50, 350, 350), stream=img_bytes)
        # Place image 2 at (200, 50, 500, 350) -> Area 90,000, 50% horizontal overlap
        page.insert_image(fitz.Rect(200, 50, 500, 350), stream=img_bytes)

        # Native text so page isn't considered scanned
        page.insert_textbox(fitz.Rect(50, 400, 550, 500), "Native explanatory caption for figures.", fontsize=11)

        doc.save(str(pdf_path))
        doc.close()

        parsed = self.parser.parse_file(pdf_path, document_id="overlap_test")
        diag = parsed.diagnostics.page_diagnostics[0]

        # Union area: 90,000 + 90,000 - 45,000 (overlap) = 135,000
        # Expected coverage ratio: 135,000 / 480,000 = 0.28125 -> round 0.2812
        # Naive sum would be 180,000 / 480,000 = 0.3750
        self.assertAlmostEqual(diag.image_coverage_ratio, 0.2812, places=3)
        self.assertLess(diag.image_coverage_ratio, 0.35, "Coverage should not double-count overlapping area")
        self.assertGreaterEqual(diag.image_coverage_ratio, 0.0)
        self.assertLessEqual(diag.image_coverage_ratio, 1.0)

    def test_genuine_merged_cells_table(self):
        """
        Tests extraction of a genuine merged-cell table where Header Row 0 has a merged cell
        spanning columns 1 & 2 (colspan=2). Verifies pdfplumber's actual extraction representation
        (None in subsumed slots, sanitized to empty string "") while documenting that semantic
        composite-header tree synthesis remains unsupported in Phase 3.1.
        """
        pdf_path = self.temp_dir / "genuine_merged_cells.pdf"
        doc = fitz.open()
        page = doc.new_page(width=600, height=800)

        # Draw a table grid with merged cell in row 0 across col 1 and 2:
        # Col 0: x in [50, 200]
        # Col 1+2 (Merged!): x in [200, 500] (divider at x=350 only exists in row 1!)
        page.draw_line(fitz.Point(50, 100), fitz.Point(500, 100))
        page.draw_line(fitz.Point(50, 140), fitz.Point(500, 140))
        page.draw_line(fitz.Point(50, 180), fitz.Point(500, 180))

        page.draw_line(fitz.Point(50, 100), fitz.Point(50, 180))
        page.draw_line(fitz.Point(200, 100), fitz.Point(200, 180))
        page.draw_line(fitz.Point(350, 140), fitz.Point(350, 180))  # Row 1 divider only
        page.draw_line(fitz.Point(500, 100), fitz.Point(500, 180))

        # Text in merged header:
        page.insert_textbox(fitz.Rect(55, 105, 195, 135), "Regulated Entity", fontsize=10)
        page.insert_textbox(fitz.Rect(205, 105, 495, 135), "Prudential Capital Norms", fontsize=10)

        # Text in row 1:
        page.insert_textbox(fitz.Rect(55, 145, 195, 175), "Commercial Banks", fontsize=10)
        page.insert_textbox(fitz.Rect(205, 145, 345, 175), "Tier 1: 9.0%", fontsize=10)
        page.insert_textbox(fitz.Rect(355, 145, 495, 175), "Tier 2: 2.5%", fontsize=10)

        doc.save(str(pdf_path))
        doc.close()

        parsed = self.parser.parse_file(pdf_path, document_id="merged_cells_test")
        tables = parsed.get_tables()
        self.assertEqual(len(tables), 1, "Expected 1 table extracted")

        table_block = tables[0]
        grid = table_block.table_data
        self.assertEqual(len(grid), 2)  # 2 rows
        self.assertEqual(len(grid[0]), 3)  # 3 columns normalized

        # Verify physical extraction representation:
        # Col 0: 'Regulated Entity', Col 1: 'Prudential Capital Norms', Col 2 (subsumed slot): ''
        self.assertEqual(grid[0][0], "Regulated Entity")
        self.assertEqual(grid[0][1], "Prudential Capital Norms")
        self.assertEqual(grid[0][2], "", "Subsumed merged cell slot must be represented as empty string")

        # Row 1 has all 3 columns filled
        self.assertEqual(grid[1][0], "Commercial Banks")
        self.assertEqual(grid[1][1], "Tier 1: 9.0%")
        self.assertEqual(grid[1][2], "Tier 2: 2.5%")

        # Markdown representation retains 3 columns without crashing
        self.assertIn("| Regulated Entity | Prudential Capital Norms |  |", table_block.table_markdown)
        self.assertIn("| Commercial Banks | Tier 1: 9.0% | Tier 2: 2.5% |", table_block.table_markdown)


if __name__ == "__main__":
    unittest.main()

