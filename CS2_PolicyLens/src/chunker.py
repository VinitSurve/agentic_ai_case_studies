"""
PolicyLens (Case Study 2) – Regulatory Document Chunker

Implements regulatory-document-aware chunking:
- Structure-aware chunking preserving paragraph boundaries, hierarchical breadcrumbs,
  and markdown table serialization within strict token budgets.
- Fixed-window sliding chunking for benchmark baseline comparisons.
- Full provenance tracking mapping constituent block IDs to chunks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from CS2_PolicyLens.src.config import config
from CS2_PolicyLens.src.models import BlockType, ParsedBlock, ParsedDocument


@dataclass
class DocumentChunk:
    chunk_id: str
    document_id: str
    collection_name: str
    index_fingerprint: str
    version_id: str
    chunk_index: int
    text: str
    primary_block_ids: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)
    token_count: int = 0


class RegulatoryChunker:
    """
    Splits ParsedDocument instances into indexed chunks respecting regulatory structure
    or fixed sliding-window baselines.
    """

    def __init__(
        self,
        target_body_tokens: int = 350,
        max_embedding_tokens: int = 448,
        fixed_chunk_size: int = 500,
        fixed_chunk_overlap: int = 50,
    ) -> None:
        self.target_body_tokens = target_body_tokens
        self.max_embedding_tokens = max_embedding_tokens
        self.fixed_chunk_size = fixed_chunk_size
        self.fixed_chunk_overlap = fixed_chunk_overlap

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Lightweight token estimator: approx 1.3 tokens per whitespace-separated word."""
        if not text:
            return 0
        words = len(re.findall(r"\S+", text))
        return max(1, int(words * 1.3))

    @staticmethod
    def _is_major_chapter_heading(text: str) -> bool:
        """
        Detects major CHAPTER headings (e.g., 'Chapter II: Classification as Non-Performing Asset',
        'Chapter-I: Preliminary', 'CHAPTER III – EXPOSURE CLASSES AND RISK WEIGHTS').

        Reliably rejects:
        - Prose references (e.g., 'Chapter III, whose...', 'Chapter II of these Directions')
        - Table of Contents lines (dot-leaders or trailing page numbers e.g. '... 4', '\n3')
        - Sentences containing mid-block sentence breaks or trailing periods
        """
        stripped = text.strip()

        # 1. Match 'CHAPTER' followed by space/dash/en-dash and Roman or Arabic numerals
        m = re.match(
            r"^CHAPTER[\s\-–—]+([IVXLCDM]+|\d+)\b(.*)",
            stripped,
            re.IGNORECASE | re.DOTALL,
        )
        if not m:
            return False

        rest = m.group(2).strip()

        # 2. Reject prose references
        # Comma immediately following numeral (e.g., 'Chapter III, whose...')
        if rest.startswith(","):
            return False
        # Prepositions indicating a reference rather than a title (e.g., 'Chapter II of these Directions')
        if re.match(r"^(of|under|in|for)\b", rest, re.IGNORECASE):
            return False
        # Headings do not end in a period or semicolon
        if stripped.endswith(".") or stripped.endswith(";"):
            return False
        # Headings do not contain mid-string sentence breaks (e.g., '...rates. Such')
        if re.search(r"\.\s+[A-Z]", rest):
            return False

        # 3. Reject Table of Contents entries terminating in a page number
        # Dot leaders / ellipses followed by page number: '... 4' or '…… 16'
        if re.search(r"(\.{2,}|…+)\s*\d+$", stripped):
            return False
        # Linebreak or wide tabular spacing followed by page number: '\n3', '   8'
        if re.search(r"(\n|\s{2,})\d+$", stripped):
            return False

        return True

    def chunk(
        self,
        parsed_doc: ParsedDocument,
        collection_name: str,
        index_fingerprint: str,
        version_id: str,
    ) -> list[DocumentChunk]:
        """
        Main chunking dispatch: calls structure-aware or fixed chunker based on collection.
        """
        if collection_name == config.COLLECTION_FIXED:
            return self._chunk_fixed(parsed_doc, collection_name, index_fingerprint, version_id)
        return self._chunk_structure_aware(parsed_doc, collection_name, index_fingerprint, version_id)

    def _chunk_structure_aware(
        self,
        parsed_doc: ParsedDocument,
        collection_name: str,
        index_fingerprint: str,
        version_id: str,
    ) -> list[DocumentChunk]:
        """
        Structure-aware chunking preserving section hierarchy, table markdown,
        and paragraph coherence.
        """
        chunks: list[DocumentChunk] = []
        doc_id = parsed_doc.document_id
        current_heading = "General Provisions"
        
        current_block_ids: list[str] = []
        current_text_segments: list[str] = []
        current_pages: set[int] = set()
        current_tokens = 0
        chunk_idx = 0

        def emit_current_chunk() -> None:
            nonlocal chunk_idx, current_tokens, current_block_ids, current_text_segments, current_pages
            if not current_text_segments:
                return

            body_text = "\n\n".join(current_text_segments).strip()
            breadcrumb = f"[{doc_id} > {current_heading}]\n\n"
            full_text = breadcrumb + body_text
            chunk_tokens = self.estimate_tokens(full_text)

            chunk_id = f"{doc_id}_struct_{chunk_idx:04d}"
            meta = {
                "document_id": doc_id,
                "collection_name": collection_name,
                "index_fingerprint": index_fingerprint,
                "version_id": version_id,
                "chunk_index": chunk_idx,
                "page_number": min(current_pages) if current_pages else 1,
                "section_heading": current_heading,
                "block_count": len(current_block_ids),
                "strategy": "structure_aware",
            }
            if parsed_doc.metadata:
                if "title" in parsed_doc.metadata and parsed_doc.metadata["title"]:
                    meta["title"] = str(parsed_doc.metadata["title"])
                if "issuer" in parsed_doc.metadata and parsed_doc.metadata["issuer"]:
                    meta["issuer"] = str(parsed_doc.metadata["issuer"])

            chunks.append(
                DocumentChunk(
                    chunk_id=chunk_id,
                    document_id=doc_id,
                    collection_name=collection_name,
                    index_fingerprint=index_fingerprint,
                    version_id=version_id,
                    chunk_index=chunk_idx,
                    text=full_text,
                    primary_block_ids=list(current_block_ids),
                    metadata=meta,
                    token_count=chunk_tokens,
                )
            )
            chunk_idx += 1
            current_block_ids = []
            current_text_segments = []
            current_pages = set()
            current_tokens = 0

        for block in parsed_doc.blocks:
            # Skip empty or whitespace blocks
            block_text = (block.text or "").strip()
            if not block_text and not block.table_markdown:
                continue

            # Flush pending chunk and update heading context on major CHAPTER boundaries
            if block.block_type in (BlockType.TITLE, BlockType.HEADING):
                if self._is_major_chapter_heading(block_text):
                    emit_current_chunk()
                if len(block_text) < 120 and not block_text.endswith("."):
                    if not re.match(r"^\([a-z\d]+\)\s+", block_text, re.IGNORECASE):
                        current_heading = block_text

            # Handle Table Blocks
            if block.block_type == BlockType.TABLE and block.table_markdown:
                # Tables form their own standalone chunk to preserve markdown structure
                emit_current_chunk()
                table_text = block.table_markdown
                table_tokens = self.estimate_tokens(table_text)
                
                chunk_id = f"{doc_id}_struct_{chunk_idx:04d}"
                breadcrumb = f"[{doc_id} > {current_heading} (Table)]\n\n"
                full_table_text = breadcrumb + table_text

                meta = {
                    "document_id": doc_id,
                    "collection_name": collection_name,
                    "index_fingerprint": index_fingerprint,
                    "version_id": version_id,
                    "chunk_index": chunk_idx,
                    "page_number": block.page_number,
                    "section_heading": current_heading,
                    "block_type": "table",
                    "strategy": "structure_aware",
                }

                chunks.append(
                    DocumentChunk(
                        chunk_id=chunk_id,
                        document_id=doc_id,
                        collection_name=collection_name,
                        index_fingerprint=index_fingerprint,
                        version_id=version_id,
                        chunk_index=chunk_idx,
                        text=full_table_text,
                        primary_block_ids=[block.block_id],
                        metadata=meta,
                        token_count=self.estimate_tokens(full_table_text),
                    )
                )
                chunk_idx += 1
                continue

            # Standard Text Blocks (Paragraphs, List items, etc.)
            block_tokens = self.estimate_tokens(block_text)

            # If adding this block exceeds target budget, emit current chunk first
            if current_tokens + block_tokens > self.target_body_tokens and current_text_segments:
                emit_current_chunk()

            current_text_segments.append(block_text)
            current_block_ids.append(block.block_id)
            current_pages.add(block.page_number)
            current_tokens += block_tokens

            # If single block itself exceeds target tokens, emit immediately
            if current_tokens >= self.target_body_tokens:
                emit_current_chunk()

        # Emit remaining buffered content
        emit_current_chunk()
        return chunks

    def _chunk_fixed(
        self,
        parsed_doc: ParsedDocument,
        collection_name: str,
        index_fingerprint: str,
        version_id: str,
    ) -> list[DocumentChunk]:
        """
        Fixed sliding window baseline: splits concatenated text into fixed-size token windows.
        """
        chunks: list[DocumentChunk] = []
        doc_id = parsed_doc.document_id

        # Concatenate substantive blocks
        ordered_blocks = [b for b in parsed_doc.blocks if (b.text or "").strip()]
        if not ordered_blocks:
            return chunks

        all_words: list[tuple[str, str, int]] = []  # (word, block_id, page_number)
        for b in ordered_blocks:
            words = (b.text or "").split()
            for w in words:
                all_words.append((w, b.block_id, b.page_number))

        if not all_words:
            return chunks

        step = max(1, self.fixed_chunk_size - self.fixed_chunk_overlap)
        chunk_idx = 0

        for i in range(0, len(all_words), step):
            window_slice = all_words[i : i + self.fixed_chunk_size]
            if not window_slice:
                continue

            window_words = [w[0] for w in window_slice]
            window_text = " ".join(window_words)
            chunk_tokens = self.estimate_tokens(window_text)

            # Find distinct constituent blocks in this window
            seen_blocks = []
            pages = set()
            for w in window_slice:
                if w[1] not in seen_blocks:
                    seen_blocks.append(w[1])
                pages.add(w[2])

            chunk_id = f"{doc_id}_fixed_{chunk_idx:04d}"
            meta = {
                "document_id": doc_id,
                "collection_name": collection_name,
                "index_fingerprint": index_fingerprint,
                "version_id": version_id,
                "chunk_index": chunk_idx,
                "page_number": min(pages) if pages else 1,
                "strategy": "fixed_sliding_window",
            }
            if parsed_doc.metadata:
                if "title" in parsed_doc.metadata and parsed_doc.metadata["title"]:
                    meta["title"] = str(parsed_doc.metadata["title"])
                if "issuer" in parsed_doc.metadata and parsed_doc.metadata["issuer"]:
                    meta["issuer"] = str(parsed_doc.metadata["issuer"])

            chunks.append(
                DocumentChunk(
                    chunk_id=chunk_id,
                    document_id=doc_id,
                    collection_name=collection_name,
                    index_fingerprint=index_fingerprint,
                    version_id=version_id,
                    chunk_index=chunk_idx,
                    text=window_text,
                    primary_block_ids=seen_blocks,
                    metadata=meta,
                    token_count=chunk_tokens,
                )
            )
            chunk_idx += 1

            if i + self.fixed_chunk_size >= len(all_words):
                break

        return chunks

