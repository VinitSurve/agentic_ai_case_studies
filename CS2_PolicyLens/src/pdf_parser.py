"""
PolicyLens (Case Study 2) – Unified PDF Parser & Layout Analysis Engine

Orchestrates PyMuPDF, pdfplumber, and Tesseract OCR to extract native text,
preserve table structures, reconstruct reading order for multi-column layouts,
and provide OCR fallbacks for scanned pages and embedded image regions.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from statistics import median
from typing import Any, Sequence

import pdfplumber
import pymupdf as fitz

from CS2_PolicyLens.src.config import config
from CS2_PolicyLens.src.layout_analyzer import LayoutAnalyzer
from CS2_PolicyLens.src.models import (
    BlockType,
    BoundingBox,
    DocumentDiagnostics,
    ExtractionMethod,
    PageDiagnostics,
    ParsedBlock,
    ParsedDocument,
)
from CS2_PolicyLens.src.ocr_engine import OCREngine
from CS2_PolicyLens.src.table_extractor import TableExtractor

logger = logging.getLogger("PolicyLens.PDFParser")


class PDFParser:
    def __init__(
        self,
        ocr_engine: OCREngine | None = None,
        table_extractor: TableExtractor | None = None,
        layout_analyzer: LayoutAnalyzer | None = None,
    ):
        self.ocr_engine = ocr_engine or OCREngine()
        self.table_extractor = table_extractor or TableExtractor()
        self.layout_analyzer = layout_analyzer or LayoutAnalyzer()

    def parse_file(
        self, pdf_path: str | Path, document_id: str | None = None
    ) -> ParsedDocument:
        """Parses a local PDF file into a structured ParsedDocument."""
        path = Path(pdf_path)
        if not path.is_file():
            raise FileNotFoundError(f"PDF file not found: {path}")

        doc_id = document_id or path.stem
        with open(path, "rb") as f:
            pdf_bytes = f.read()

        return self.parse_bytes(pdf_bytes, doc_id, filename=path.name)

    def parse_bytes(
        self, pdf_bytes: bytes, document_id: str, filename: str | None = None
    ) -> ParsedDocument:
        """
        Parses raw PDF bytes into a structured ParsedDocument.
        
        Guarantees deterministic reading order, table schema preservation,
        and OCR fallback diagnostics.
        """
        fitz_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_pages = len(fitz_doc)

        plumber_doc = None
        try:
            import io
            plumber_doc = pdfplumber.open(io.BytesIO(pdf_bytes))
        except Exception as e:
            logger.warning(f"[{document_id}] Failed to open PDF with pdfplumber: {e}")

        all_blocks: list[ParsedBlock] = []
        page_diagnostics_list: list[PageDiagnostics] = []
        parsing_errors: list[str] = []

        ocr_page_count = 0
        ocr_region_count = 0
        total_tables = 0

        for page_idx in range(total_pages):
            page_number = page_idx + 1
            fitz_page = fitz_doc[page_idx]
            plumber_page = (
                plumber_doc.pages[page_idx]
                if (plumber_doc and page_idx < len(plumber_doc.pages))
                else None
            )

            try:
                page_blocks, p_diag = self._parse_single_page(
                    fitz_page=fitz_page,
                    plumber_page=plumber_page,
                    document_id=document_id,
                    page_number=page_number,
                )
                all_blocks.extend(page_blocks)
                page_diagnostics_list.append(p_diag)

                if p_diag.ocr_applied and p_diag.is_scanned:
                    ocr_page_count += 1
                ocr_region_count += sum(
                    1 for b in page_blocks if b.block_type == BlockType.OCR_REGION
                )
                total_tables += p_diag.tables_detected

            except Exception as e:
                err_msg = f"Error parsing page {page_number}: {e}"
                logger.error(f"[{document_id}] {err_msg}", exc_info=True)
                parsing_errors.append(err_msg)
                self._log_failure(document_id, page_number, str(e))

        fitz_doc.close()
        if plumber_doc:
            plumber_doc.close()

        doc_diagnostics = DocumentDiagnostics(
            document_id=document_id,
            total_pages=total_pages,
            ocr_page_count=ocr_page_count,
            ocr_region_count=ocr_region_count,
            table_count=total_tables,
            total_blocks=len(all_blocks),
            page_diagnostics=page_diagnostics_list,
            parsing_errors=parsing_errors,
        )

        return ParsedDocument(
            document_id=document_id,
            total_pages=total_pages,
            blocks=all_blocks,
            diagnostics=doc_diagnostics,
            metadata={"filename": filename or f"{document_id}.pdf"},
        )

    def _parse_single_page(
        self,
        fitz_page: fitz.Page,
        plumber_page: pdfplumber.page.Page | None,
        document_id: str,
        page_number: int,
    ) -> tuple[list[ParsedBlock], PageDiagnostics]:
        """Parses a single PDF page handling native text, tables, and OCR fallbacks."""
        page_rect = fitz_page.rect
        page_width = page_rect.width
        page_height = page_rect.height

        raw_native_text = fitz_page.get_text() or ""
        needs_ocr, trigger_reason, ocr_stats = self.ocr_engine.detect_ocr_need(
            fitz_page, raw_native_text
        )

        # ---------------------------------------------------------------------
        # PATH A: FULL-PAGE OCR (Scanned / Poor Quality Pages)
        # ---------------------------------------------------------------------
        if needs_ocr:
            ocr_blocks, mean_conf, ocr_diag = self.ocr_engine.ocr_full_page(
                fitz_page, document_id, page_number, trigger_reason or "unknown"
            )
            ordered_blocks, layout_type = self.layout_analyzer.reconstruct_reading_order(
                ocr_blocks, page_width, page_height
            )

            p_diag = PageDiagnostics(
                document_id=document_id,
                page_number=page_number,
                width=round(page_width, 2),
                height=round(page_height, 2),
                is_scanned=True,
                native_char_count=len(raw_native_text.strip()),
                image_count=ocr_stats.get("image_count", 0),
                image_coverage_ratio=ocr_stats.get("image_coverage_ratio", 0.0),
                ocr_applied=True,
                ocr_trigger_reason=trigger_reason,
                ocr_mean_confidence=round(mean_conf, 4),
                layout_type=layout_type,
                tables_detected=0,
                blocks_count=len(ordered_blocks),
                warnings=["Full-page OCR fallback triggered"],
            )
            return ordered_blocks, p_diag

        # ---------------------------------------------------------------------
        # PATH B: NATIVE TEXT + STRUCTURED TABLES + REGIONAL OCR
        # ---------------------------------------------------------------------
        # 1. Extract Structured Tables via pdfplumber
        table_blocks: list[ParsedBlock] = []
        table_bboxes: list[BoundingBox] = []
        if plumber_page is not None:
            table_blocks = self.table_extractor.extract_page_tables(
                plumber_page, document_id, page_number
            )
            for tbl in table_blocks:
                bx0, by0, bx1, by1 = tbl.bounding_box
                table_bboxes.append(BoundingBox(bx0, by0, bx1, by1))

        # 2. Extract Native Text Blocks with PyMuPDF get_text('dict')
        page_dict = fitz_page.get_text("dict")
        font_sizes: list[float] = []

        # First pass: collect font sizes for median calculation
        for b in page_dict.get("blocks", []):
            if b.get("type") == 0:  # text block
                for line in b.get("lines", []):
                    for span in line.get("spans", []):
                        if span.get("text", "").strip():
                            font_sizes.append(float(span.get("size", 10.0)))

        median_font_size = median(font_sizes) if font_sizes else 10.0

        native_blocks: list[ParsedBlock] = []
        block_counter = 0

        for b in page_dict.get("blocks", []):
            if b.get("type") != 0:  # Skip non-text blocks
                continue

            bx0, by0, bx1, by1 = b.get("bbox", (0.0, 0.0, 0.0, 0.0))
            block_box = BoundingBox(bx0, by0, bx1, by1)

            # Suppress native text if it lies inside an extracted table
            suppress = False
            for t_box in table_bboxes:
                if t_box.contains(block_box, tolerance=3.0) or t_box.overlaps(block_box, threshold=0.60):
                    suppress = True
                    break

            if suppress:
                continue

            # Reconstruct paragraph lines and typography
            lines_text: list[str] = []
            span_sizes: list[float] = []
            is_bold = False

            for line in b.get("lines", []):
                line_spans: list[str] = []
                for span in line.get("spans", []):
                    span_text = span.get("text", "")
                    if span_text:
                        line_spans.append(span_text)
                        span_sizes.append(float(span.get("size", 10.0)))
                        flags = int(span.get("flags", 0))
                        font_name = str(span.get("font", "")).lower()
                        if (flags & 2 != 0) or ("bold" in font_name) or ("black" in font_name):
                            is_bold = True

                line_combined = "".join(line_spans).strip()
                if line_combined:
                    lines_text.append(line_combined)

            full_block_text = "\n".join(lines_text).strip()
            if not full_block_text:
                continue

            block_font_size = median(span_sizes) if span_sizes else median_font_size

            # Semantic classification
            block_type = self.layout_analyzer.classify_block_type(
                text=full_block_text,
                bbox=(bx0, by0, bx1, by1),
                font_size=block_font_size,
                is_bold=is_bold,
                median_font_size=median_font_size,
                page_height=page_height,
                page_number=page_number,
                is_first_block=(block_counter == 0),
                page_width=page_width,
            )

            block_id = f"{document_id}_p{page_number}_b{block_counter}"
            native_blocks.append(
                ParsedBlock(
                    document_id=document_id,
                    page_number=page_number,
                    block_id=block_id,
                    block_type=block_type,
                    text=full_block_text,
                    bounding_box=(round(bx0, 2), round(by0, 2), round(bx1, 2), round(by1, 2)),
                    reading_order=0,  # Ordered below
                    extraction_method=ExtractionMethod.NATIVE_TEXT,
                    confidence=1.0,
                    metadata={
                        "font_size": round(block_font_size, 2),
                        "is_bold": is_bold,
                    },
                )
            )
            block_counter += 1

        # 3. Check for Regional OCR in embedded scanned images
        existing_bboxes = [
            BoundingBox(*b.bounding_box) for b in native_blocks
        ] + table_bboxes
        ocr_region_blocks = self.ocr_engine.extract_ocr_regions(
            fitz_page, document_id, page_number, existing_bboxes
        )

        # 4. Combine all blocks and reconstruct reading order
        combined_blocks = native_blocks + table_blocks + ocr_region_blocks
        ordered_blocks, layout_type = self.layout_analyzer.reconstruct_reading_order(
            combined_blocks, page_width, page_height
        )

        p_diag = PageDiagnostics(
            document_id=document_id,
            page_number=page_number,
            width=round(page_width, 2),
            height=round(page_height, 2),
            is_scanned=False,
            native_char_count=len(raw_native_text.strip()),
            image_count=ocr_stats.get("image_count", 0),
            image_coverage_ratio=ocr_stats.get("image_coverage_ratio", 0.0),
            ocr_applied=(len(ocr_region_blocks) > 0),
            ocr_trigger_reason="embedded_image_region" if ocr_region_blocks else None,
            ocr_mean_confidence=1.0,
            layout_type=layout_type,
            tables_detected=len(table_blocks),
            blocks_count=len(ordered_blocks),
            warnings=["Genuinely blank page; OCR bypassed"] if ocr_stats.get("is_blank") else [],
        )

        return ordered_blocks, p_diag

    def _log_failure(self, document_id: str, page_number: int, error_message: str) -> None:
        """Records parsing errors to logs/ingestion_failures.jsonl without throwing away content."""
        try:
            log_path = config.FAILURES_LOG
            log_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "document_id": document_id,
                "page_number": page_number,
                "error": error_message,
            }
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception:
            pass
