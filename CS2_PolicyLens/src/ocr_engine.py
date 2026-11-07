"""
PolicyLens (Case Study 2) – OCR Engine Module

Provides OCR detection and execution via Tesseract, supporting:
1. Full-page OCR fallback for scanned or poor-quality pages.
2. Regional OCR for embedded scanned images/stamps on hybrid native-text pages.
3. Diagnostic logging and word-level confidence scoring.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Sequence

import PIL.Image as PILImage
import pymupdf as fitz
import pytesseract
from pytesseract import Output

from CS2_PolicyLens.src.config import config
from CS2_PolicyLens.src.models import (
    BlockType,
    BoundingBox,
    ExtractionMethod,
    ParsedBlock,
)

logger = logging.getLogger("PolicyLens.OCREngine")


class OCREngine:
    def __init__(self, tesseract_cmd: str | None = None, dpi: int | None = None):
        self.tesseract_cmd = tesseract_cmd or config.TESSERACT_CMD
        self.dpi = dpi or config.OCR_DPI
        pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd

    @staticmethod
    def calculate_rectangles_union_area(
        rects: Sequence[tuple[float, float, float, float]]
    ) -> float:
        """
        Calculates the exact area of the 2D union of axis-aligned rectangles
        using a 1D sweep-line algorithm to eliminate double-counting of overlapping regions.
        """
        if not rects:
            return 0.0

        # Unique X coordinates defining vertical slices
        x_coords = sorted(list({round(r[0], 2) for r in rects} | {round(r[2], 2) for r in rects}))
        total_union_area = 0.0

        for i in range(len(x_coords) - 1):
            x_left = x_coords[i]
            x_right = x_coords[i + 1]
            slice_width = x_right - x_left
            if slice_width <= 0:
                continue

            # Active rectangles intersecting this vertical slice
            y_intervals: list[tuple[float, float]] = []
            for r in rects:
                if r[0] <= x_left and r[2] >= x_right:
                    y_intervals.append((r[1], r[3]))

            if not y_intervals:
                continue

            # Merge 1D Y-intervals
            y_intervals.sort(key=lambda iv: iv[0])
            merged: list[tuple[float, float]] = [y_intervals[0]]
            for cur in y_intervals[1:]:
                prev_start, prev_end = merged[-1]
                if cur[0] <= prev_end:
                    merged[-1] = (prev_start, max(prev_end, cur[1]))
                else:
                    merged.append(cur)

            slice_height = sum(end - start for start, end in merged)
            total_union_area += slice_width * slice_height

        return total_union_area

    def detect_ocr_need(
        self, page: fitz.Page, native_text: str
    ) -> tuple[bool, str | None, dict[str, Any]]:
        """
        Evaluates whether a page requires full-page OCR fallback.
        
        The decision accounts for:
        1. Distinguishing genuinely blank pages from scanned pages (checks for substantive raster images).
        2. Exact union coverage of image rectangles (avoiding double-counting overlapping images).
        3. Low native text character counts (< OCR_MIN_TEXT_CHARS) when substantive raster graphics exist.
        4. High image coverage ratio (>= OCR_IMAGE_COVERAGE_RATIO).
        5. Garbled native text / high replacement character density.
        """
        page_rect = page.rect
        page_area = max(1.0, page_rect.width * page_rect.height)
        native_chars = len(native_text.strip())

        images = page.get_images(full=True)
        image_count = len(images)

        # Collect image bounding boxes on the page
        image_rects: list[tuple[float, float, float, float]] = []
        for img_info in images:
            xref = img_info[0]
            try:
                rects = page.get_image_rects(xref)
                for r in rects:
                    if r.width > 0 and r.height > 0:
                        image_rects.append((r.x0, r.y0, r.x1, r.y1))
            except Exception:
                continue

        # Calculate exact union area without inflating overlapping image rectangles
        union_image_area = self.calculate_rectangles_union_area(image_rects)
        coverage_ratio = min(1.0, max(0.0, union_image_area / page_area))

        # Check for substantive images (width >= 60 and height >= 60 or area >= 3600 pt^2)
        has_substantive_image = any(
            (r[2] - r[0] >= 60 and r[3] - r[1] >= 60) or ((r[2] - r[0]) * (r[3] - r[1]) >= 3600)
            for r in image_rects
        )

        # Garbled characters check
        replacement_chars = native_text.count("\ufffd") + len(
            re.findall(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", native_text)
        )
        garbled_ratio = (replacement_chars / max(1, native_chars)) if native_chars > 0 else 0.0

        stats: dict[str, Any] = {
            "native_char_count": native_chars,
            "image_count": image_count,
            "image_coverage_ratio": round(coverage_ratio, 4),
            "garbled_ratio": round(garbled_ratio, 4),
            "has_substantive_image": has_substantive_image,
        }

        # ---------------------------------------------------------------------
        # TRIGGER DECISIONS
        # ---------------------------------------------------------------------
        # Fix 1: Distinguish genuinely blank pages from scanned pages
        if native_chars == 0:
            if image_count == 0 or not has_substantive_image:
                # Genuinely blank page or only tiny decorative mark -> DO NOT run OCR!
                stats["is_blank"] = True
                return False, None, stats
            # Scanned page: has 0 native text characters but has substantive raster image content
            stats["is_blank"] = False
            return True, "scanned_raster_page", stats

        # If page has very little native text (< OCR_MIN_TEXT_CHARS)
        if native_chars < config.OCR_MIN_TEXT_CHARS:
            # Only trigger OCR if there is substantive image content that likely holds scanned text
            if image_count > 0 and (has_substantive_image or coverage_ratio >= 0.05):
                return True, "low_native_chars_with_images", stats
            # Short text with no substantive images: not scanned, e.g. cover spacer or title fragment
            return False, None, stats

        # High image coverage with low native text
        if coverage_ratio >= config.OCR_IMAGE_COVERAGE_RATIO and native_chars < 150:
            return True, "high_image_coverage_low_text", stats

        # Garbled native text layer
        if garbled_ratio > 0.30 and native_chars < 200:
            return True, "garbled_text_layer", stats

        return False, None, stats

    def ocr_full_page(
        self,
        page: fitz.Page,
        document_id: str,
        page_number: int,
        trigger_reason: str,
    ) -> tuple[list[ParsedBlock], float, dict[str, Any]]:
        """
        Performs full-page OCR on a scanned or poor-quality page.
        Returns extracted blocks, mean confidence score (0.0 - 1.0), and diagnostics.
        """
        page_rect = page.rect
        scale_dpi = self.dpi
        pix = page.get_pixmap(dpi=scale_dpi)
        img = PILImage.open(io.BytesIO(pix.tobytes("png")))

        scale_x = page_rect.width / max(1.0, img.width)
        scale_y = page_rect.height / max(1.0, img.height)

        try:
            data = pytesseract.image_to_data(img, output_type=Output.DICT)
        except Exception as e:
            logger.warning(
                f"[{document_id}:p{page_number}] Tesseract image_to_data failed: {e}. Falling back to image_to_string."
            )
            raw_text = pytesseract.image_to_string(img).strip()
            conf = 0.50 if raw_text else 0.0
            block = ParsedBlock(
                document_id=document_id,
                page_number=page_number,
                block_id=f"{document_id}_p{page_number}_ocr0",
                block_type=BlockType.PARAGRAPH,
                text=raw_text,
                bounding_box=(0.0, 0.0, page_rect.width, page_rect.height),
                reading_order=0,
                extraction_method=ExtractionMethod.OCR_PAGE,
                confidence=conf,
                metadata={"trigger_reason": trigger_reason},
            )
            self._log_diagnostic(document_id, page_number, trigger_reason, conf, 1)
            return [block], conf, {"mean_confidence": conf, "word_count": len(raw_text.split())}

        # Group words by block_num and par_num
        grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
        confidences: list[float] = []

        n_boxes = len(data["text"])
        for i in range(n_boxes):
            word = data["text"][i].strip()
            conf_val = float(data["conf"][i])
            if not word or conf_val < 0:
                continue

            confidences.append(conf_val)
            key = (data["block_num"][i], data["par_num"][i])
            grouped.setdefault(key, []).append(
                {
                    "word": word,
                    "x0": data["left"][i] * scale_x,
                    "y0": data["top"][i] * scale_y,
                    "x1": (data["left"][i] + data["width"][i]) * scale_x,
                    "y1": (data["top"][i] + data["height"][i]) * scale_y,
                    "conf": conf_val / 100.0,
                }
            )

        mean_conf = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
        blocks: list[ParsedBlock] = []

        for idx, ((b_num, p_num), words) in enumerate(sorted(grouped.items())):
            text = " ".join(w["word"] for w in words).strip()
            if not text:
                continue

            x0 = min(w["x0"] for w in words)
            y0 = min(w["y0"] for w in words)
            x1 = max(w["x1"] for w in words)
            y1 = max(w["y1"] for w in words)
            block_conf = sum(w["conf"] for w in words) / len(words)

            # Classify block type based on geometry and heading heuristics
            b_type = BlockType.PARAGRAPH
            if idx == 0 and y0 < page_rect.height * 0.20 and len(text.split()) <= 15:
                b_type = BlockType.TITLE
            elif len(text.split()) <= 12 and (
                re.match(r"^(\d+\.|\([a-z0-9]+\)|Section|Clause|Chapter)\s+", text, re.I)
                or text.isupper()
            ):
                b_type = BlockType.HEADING

            blocks.append(
                ParsedBlock(
                    document_id=document_id,
                    page_number=page_number,
                    block_id=f"{document_id}_p{page_number}_ocr{idx}",
                    block_type=b_type,
                    text=text,
                    bounding_box=(round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)),
                    reading_order=idx,
                    extraction_method=ExtractionMethod.OCR_PAGE,
                    confidence=round(block_conf, 4),
                    metadata={
                        "tesseract_block": b_num,
                        "tesseract_par": p_num,
                        "trigger_reason": trigger_reason,
                    },
                )
            )

        diagnostics = {
            "mean_confidence": round(mean_conf, 4),
            "word_count": len(confidences),
            "block_count": len(blocks),
            "trigger_reason": trigger_reason,
        }
        self._log_diagnostic(document_id, page_number, trigger_reason, mean_conf, len(blocks))
        return blocks, mean_conf, diagnostics

    def extract_ocr_regions(
        self,
        page: fitz.Page,
        document_id: str,
        page_number: int,
        existing_text_bboxes: list[BoundingBox],
    ) -> list[ParsedBlock]:
        """
        Extracts and OCRs distinct embedded image regions on hybrid pages.
        
        Preserves native text while extracting non-empty text from embedded scanned
        images, stamps, or circular notices that do not overlap existing native text.
        """
        page_rect = page.rect
        images = page.get_images(full=True)
        if not images:
            return []

        ocr_blocks: list[ParsedBlock] = []

        for img_idx, img_info in enumerate(images):
            xref = img_info[0]
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                continue

            for rect_idx, rect in enumerate(rects):
                # Filter small icons, bullets, horizontal separator lines
                if rect.width < 50 or rect.height < 25 or (rect.width * rect.height) < 2000:
                    continue

                img_box = BoundingBox(rect.x0, rect.y0, rect.x1, rect.y1)

                # Check if region heavily overlaps native text blocks
                overlapping = False
                for t_box in existing_text_bboxes:
                    if img_box.overlaps(t_box, threshold=0.40):
                        overlapping = True
                        break

                if overlapping:
                    continue

                # Crop region and OCR
                try:
                    pix = page.get_pixmap(clip=rect, dpi=self.dpi)
                    img = PILImage.open(io.BytesIO(pix.tobytes("png")))
                    text = pytesseract.image_to_string(img).strip()
                    # Filter out noise / non-text images
                    alphanumeric_chars = len(re.findall(r"[a-zA-Z0-9]", text))
                    if alphanumeric_chars < 12:
                        continue

                    # Compute confidence
                    data = pytesseract.image_to_data(img, output_type=Output.DICT)
                    conf_vals = [float(c) for c in data["conf"] if float(c) >= 0]
                    conf = (sum(conf_vals) / len(conf_vals) / 100.0) if conf_vals else 0.70

                    block_id = f"{document_id}_p{page_number}_img{img_idx}_{rect_idx}"
                    ocr_blocks.append(
                        ParsedBlock(
                            document_id=document_id,
                            page_number=page_number,
                            block_id=block_id,
                            block_type=BlockType.OCR_REGION,
                            text=text,
                            bounding_box=img_box.as_tuple(),
                            reading_order=0,  # Will be positioned by LayoutAnalyzer
                            extraction_method=ExtractionMethod.OCR_REGION,
                            confidence=round(conf, 4),
                            metadata={
                                "image_xref": xref,
                                "region_width": round(rect.width, 2),
                                "region_height": round(rect.height, 2),
                            },
                        )
                    )
                    logger.info(
                        f"[{document_id}:p{page_number}] Extracted OCR region {block_id}: {len(text)} chars (conf {conf:.2f})"
                    )
                except Exception as e:
                    logger.debug(
                        f"[{document_id}:p{page_number}] Regional OCR failed on xref {xref}: {e}"
                    )
                    continue

        return ocr_blocks

    def _log_diagnostic(
        self,
        document_id: str,
        page_number: int,
        trigger_reason: str,
        confidence: float,
        block_count: int,
    ) -> None:
        """Appends an OCR execution record to logs/ocr_diagnostics.jsonl."""
        try:
            log_path = config.OCR_LOG
            log_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "document_id": document_id,
                "page_number": page_number,
                "trigger_reason": trigger_reason,
                "confidence": round(confidence, 4),
                "block_count": block_count,
            }
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception:
            pass
