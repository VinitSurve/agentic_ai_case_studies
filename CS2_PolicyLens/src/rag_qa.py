"""
PolicyLens (Case Study 2) – Minimal RAG Question Answering Engine

Implements Phase 3.3 RAG Question Answering:
- Retrieves strictly from active documents via SQLite-isolated ChromaDB query.
- Supports metadata and issuer filtering to constrain QA candidate retrieval and citations.
- Formulates grounded prompts requiring strict adherence to regulatory evidence.
- Supports configurable local/cloud LLMs (Groq llama-3.3-70b-versatile, qwen, etc.) with automatic fallback.
- Guarantees complete provenance citations (document_id, page_number/span, section_heading, score).
- Provides structured, faithful extractive fallback when cloud LLMs are unavailable or unconfigured.
- Evaluates evidence coverage to distinguish between complete answers, partial evidence, and insufficient context.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Sequence

from CS2_PolicyLens.src.config import config
from CS2_PolicyLens.src.indexing_pipeline import (
    build_document_where_clause,
    query_policy_corpus,
    resolve_allowed_document_ids,
)

logger = logging.getLogger("PolicyLens.RAG_QA")

SYSTEM_PROMPT = """You are PolicyLens, an authoritative regulatory compliance assistant for Indian financial institutions (RBI, SEBI, IRDAI).
Your answers must be STRICTLY grounded in the provided regulatory context.

Mandatory Rules:
1. State only facts directly supported by the context.
2. Explicitly cite source document IDs, circular references, and page numbers when stating rules.
3. Never invent regulatory dates, circular numbers, penalties, or compliance thresholds.
4. If the context does not provide sufficient evidence to answer the question, state:
   "The available indexed regulatory documents do not provide sufficient evidence to answer this question."
"""


def _load_groq_api_key() -> str | None:
    """Finds an available Groq API key from environment or project .env files."""
    for key_name in ("GROQ_API_KEY", "GROQ_API_KEY_1", "GROQ_API_KEY_2", "GROQ_API_KEY_3"):
        val = os.getenv(key_name)
        if val and val.strip():
            return val.strip()

    # Search known .env files
    env_paths = [
        config.BASE_DIR / ".env",
        config.BASE_DIR.parent / ".env",
        config.BASE_DIR.parent / "CS1_ClaimFast" / ".env",
        getattr(config, "REPO_ROOT", config.BASE_DIR.parent) / ".env",
        getattr(config, "REPO_ROOT", config.BASE_DIR.parent) / "CS1_ClaimFast" / ".env",
    ]
    for p in env_paths:
        if p.is_file():
            try:
                for line in p.read_text().splitlines():
                    line = line.strip()
                    if line.startswith("GROQ_API_KEY"):
                        parts = line.split("=", 1)
                        if len(parts) == 2 and parts[1].strip():
                            val = parts[1].strip().strip('"').strip("'")
                            if val and not val.startswith("gsk_placeholder") and not val.startswith("your_"):
                                return val
            except Exception:
                pass
    return None


def _fetch_adjacent_chunk(
    chroma_col: Any,
    primary_hit: dict[str, Any],
    direction: int,
    allowed_doc_ids: set[str] | Sequence[str] | None = None,
) -> dict[str, Any] | None:
    """
    Fetches and strictly validates an adjacent chunk from the same ChromaDB collection.

    Validation & Invariant Enforcement:
    1. direction must be -1 (predecessor) or +1 (successor).
    2. chunk_index must equal primary_index + direction exactly.
    3. document_id must match primary_hit and allowed_doc_ids.
    4. version_id must match primary_hit (preventing stale/staging leakage).
    5. index_fingerprint must match primary_hit (active version isolation).
    6. collection_name must match if specified.
    """
    if direction not in (-1, 1):
        return None
    if chroma_col is None or not hasattr(chroma_col, "get") or not callable(chroma_col.get):
        return None

    meta = primary_hit.get("metadata") or {}
    doc_id = meta.get("document_id") or primary_hit.get("document_id")
    if not doc_id:
        return None

    # Filter boundary check
    if allowed_doc_ids is not None and doc_id not in allowed_doc_ids:
        return None

    curr_idx = meta.get("chunk_index")
    chunk_id = primary_hit.get("chunk_id", "")
    if curr_idx is None and chunk_id:
        m_idx = re.search(r"_(?:struct|fixed)_(\d+)$", chunk_id)
        if m_idx:
            try:
                curr_idx = int(m_idx.group(1))
            except ValueError:
                curr_idx = None

    if curr_idx is None:
        return None

    expected_idx = curr_idx + direction
    if expected_idx < 0:
        return None

    version_id = meta.get("version_id")
    fingerprint = meta.get("index_fingerprint")
    col_name = meta.get("collection_name")
    strategy = meta.get("strategy")

    # Construct deterministic candidate ID
    candidate_id = None
    if chunk_id:
        m_prefix = re.match(r"^(.*_(?:struct|fixed)_)\d+$", chunk_id)
        if m_prefix:
            candidate_id = f"{m_prefix.group(1)}{expected_idx:04d}"

    if not candidate_id:
        strat_prefix = "struct" if strategy == "structure_aware" else "fixed"
        candidate_id = f"{doc_id}_{strat_prefix}_{expected_idx:04d}"

    res = None
    # 1. Direct candidate ID lookup
    try:
        res = chroma_col.get(ids=[candidate_id], include=["documents", "metadatas"])
    except Exception:
        res = None

    # 2. Fallback to metadata filter lookup if ID lookup returned empty
    if not res or not res.get("ids") or not res["ids"]:
        try:
            where_filter: dict[str, Any] = {
                "$and": [
                    {"document_id": doc_id},
                    {"chunk_index": expected_idx},
                ]
            }
            if version_id:
                where_filter["$and"].append({"version_id": version_id})
            if fingerprint:
                where_filter["$and"].append({"index_fingerprint": fingerprint})

            res = chroma_col.get(where=where_filter, limit=1, include=["documents", "metadatas"])
        except Exception:
            res = None

    if not res or not res.get("ids") or not res["ids"]:
        return None

    neighbor_id = res["ids"][0]
    neighbor_doc = res["documents"][0] if res.get("documents") else ""
    neighbor_meta = res["metadatas"][0] if res.get("metadatas") else {}

    # Strict Identity and Boundary Checks
    if neighbor_meta.get("document_id") != doc_id:
        return None
    if allowed_doc_ids is not None and neighbor_meta.get("document_id") not in allowed_doc_ids:
        return None
    if version_id and neighbor_meta.get("version_id") and neighbor_meta["version_id"] != version_id:
        return None
    if fingerprint and neighbor_meta.get("index_fingerprint") and neighbor_meta["index_fingerprint"] != fingerprint:
        return None
    if col_name and neighbor_meta.get("collection_name") and neighbor_meta["collection_name"] != col_name:
        return None
    if neighbor_meta.get("chunk_index") != expected_idx:
        return None

    return {
        "chunk_id": neighbor_id,
        "document_id": doc_id,
        "chunk_index": expected_idx,
        "page_number": neighbor_meta.get("page_number", primary_hit.get("page_number", 1)),
        "section_heading": neighbor_meta.get("section_heading", "General Provisions"),
        "text": neighbor_doc,
        "metadata": neighbor_meta,
        "is_expanded_neighbor": True,
    }


def _starts_with_incomplete_sentence(text: str) -> bool:
    """
    Detects whether a chunk begins mid-sentence or as an incomplete continuation.
    Indicators:
    - First substantive character after breadcrumbs is lowercase (e.g. 'category for a period...').
    - Starts with continuation punctuation: ), ], }, ,, ;, —, –.
    - Starts with dangling continuation conjunctions (and, or, but, which, that, etc.).
    """
    try:
        from CS2_PolicyLens.search import clean_masthead
        cleaned = clean_masthead(text).strip()
    except Exception:
        cleaned = text.strip()

    # Strip [doc_id > section] breadcrumb line if present
    lines = [l for l in cleaned.split("\n") if l.strip()]
    if lines and lines[0].startswith("[") and (" > " in lines[0] or lines[0].endswith("]")):
        lines = lines[1:]
    substantive = "\n".join(lines).strip()
    if not substantive:
        return False

    first_char = substantive[0]
    if first_char.islower():
        return True
    if first_char in (")", "]", "}", ",", ";", "—", "–"):
        return True
    if re.match(
        r"^(?:\([2-9]|\(\d{2,}|\([b-z]|\((?:ii|iii|iv|v|vi|vii|viii|ix|x)\)|[2-9]\)|\d{2,}\)|[b-z]\))",
        substantive,
        re.IGNORECASE,
    ):
        return True
    if re.match(
        r"^(?:and|or|but|nor|which|that|whereby|wherein|respectively)\b",
        substantive,
        re.IGNORECASE,
    ):
        return True
    return False


def _ends_with_incomplete_sentence(text: str) -> bool:
    """
    Detects whether a chunk genuinely terminates mid-sentence.
    Indicators:
    - Ends with unclosed punctuation: ,, ;, :, —, –, -, (, [, {.
    - Ends with split hyphenated word (e.g. re-, sub-).
    - Ends with dangling coordinating conjunction (and, or, but, nor, etc.).
    Note: Merely lacking a terminal period is NOT sufficient to trigger successor expansion.
    """
    try:
        from CS2_PolicyLens.search import clean_masthead
        cleaned = clean_masthead(text).strip()
    except Exception:
        cleaned = text.strip()

    if not cleaned:
        return False

    # Terminal sentence punctuation or markdown table boundary -> complete
    if cleaned.endswith((".", "?", "!", '."', ".'", ".)", ".]", "|")):
        return False

    # Explicit dangling punctuation or open bracket
    if cleaned.endswith((",", ";", ":", "—", "–", "-", "(", "[", "{")):
        return True

    # Split hyphenated word
    if re.search(r"\b\w+[-—–]\s*$", cleaned):
        return True

    # Dangling coordinating conjunction
    if re.search(r"\b(?:and|or|but|nor|whereas|wherein|whereby)\s*$", cleaned, re.IGNORECASE):
        return True

    return False


def extract_target_concepts(query: str) -> list[str]:
    """
    Extracts multi-item target concepts (e.g., 'substandard asset', 'doubtful asset', 'loss asset')
    from regulatory queries. Returns an empty list if query is single-topic.
    """
    q_clean = query.strip().rstrip("?.")
    # Multi-item target inquiry: "definitions of X, Y and Z" or "X, Y and Z under Clause..."
    m = re.search(
        r"(?:definitions?|categories|types|classification|conditions?)\s+of\s+(.+?)(?:\s+under\b|\s+in\b|$)",
        q_clean,
        re.IGNORECASE,
    )
    if m:
        target_span = m.group(1)
        items = re.split(r",\s*|\s+and\s+|\s+or\s+", target_span)
        cleaned = [
            it.strip().lower()
            for it in items
            if len(it.strip()) >= 3 and it.strip().lower() not in {"the", "a", "an", "all", "each", "both", "three"}
        ]
        if len(cleaned) >= 2:
            return cleaned

    # Explicit quotes
    quotes = re.findall(r"\"([^\"]+)\"", query)
    if len(quotes) >= 2:
        return [q.lower().strip() for q in quotes if q.strip()]

    return []


def extract_concept_excerpt(concept: str, text: str) -> str:
    """
    Extracts the substantive definition or provision sentence/clause for a concept from text.
    Strips chunk boundary markers and masthead artifacts before extraction.
    """
    try:
        from CS2_PolicyLens.search import clean_masthead
        cleaned_text = clean_masthead(text)
    except Exception:
        cleaned_text = text

    cleaned_text = re.sub(r"\[Chunk:\s*[^\]]+\]", "", cleaned_text)
    cleaned_text = re.sub(r"\[[a-zA-Z0-9_\-]+(?:\s*>[^\]]+)?\]", "", cleaned_text)

    pat_str = re.escape(concept).replace(r"\-", r"[\-\s]?")
    if "substandard" in concept:
        pat_str = r"sub[\-\s]?standard\s+asset"
    elif "doubtful" in concept:
        pat_str = r"doubtful\s+asset"
    elif "loss" in concept:
        pat_str = r"loss\s+asset"

    m = re.search(pat_str, cleaned_text, re.IGNORECASE)
    if not m:
        return ""

    start_pos = m.start()
    # If preceded by list marker (e.g. (i), (ii), 1., a.), include the marker
    prefix_m = re.search(r"((?:\([ivx\d]+\)|\b\d+\.|\([a-z]\))\s*)$", cleaned_text[:start_pos], re.IGNORECASE)
    if prefix_m:
        start_pos -= len(prefix_m.group(1))

    # Boundary to next clause or section
    rest = cleaned_text[m.end():]
    next_clause = re.search(
        r"(?:\n\s*(?:\([ivx\d]+\)|\b[A-Z]\.|\b\d+\.|\bChapter\b|\bAnnex\b)|\Z)",
        rest,
    )
    if next_clause:
        end_pos = m.end() + next_clause.start()
    else:
        end_pos = min(len(cleaned_text), m.end() + 450)

    excerpt = cleaned_text[start_pos:end_pos].strip()
    excerpt = re.sub(r"(\.)\s*\d+\s*$", r"\1", excerpt)
    excerpt = re.sub(r"\s+\d+\s*$", "", excerpt)
    return re.sub(r"\s+", " ", excerpt)


def evaluate_evidence_coverage(
    query: str,
    assembled_blocks: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """
    Evaluates whether the retrieved evidence context provides complete, partial,
    or insufficient coverage for the query.
    Returns a structured dictionary with status: 'complete', 'partial', or 'insufficient'.
    """
    target_concepts = extract_target_concepts(query)

    if target_concepts:
        found_concepts: dict[str, dict[str, Any]] = {}
        missing_concepts: list[str] = []

        for concept in target_concepts:
            concept_found = False
            for block in assembled_blocks:
                full_block_text = block.get("block_text", "")
                excerpt = extract_concept_excerpt(concept, full_block_text)
                if excerpt:
                    found_concepts[concept] = {
                        "concept": concept,
                        "excerpt": excerpt,
                        "document_id": block["document_id"],
                        "page_number": block["page_number"],
                        "section_heading": block["section_heading"],
                        "source_index": block["source_index"],
                    }
                    concept_found = True
                    break
            if not concept_found:
                missing_concepts.append(concept)

        if len(found_concepts) == len(target_concepts):
            status = "complete"
        elif len(found_concepts) > 0:
            status = "partial"
        else:
            status = "insufficient"

        return {
            "status": status,
            "target_concepts": target_concepts,
            "found_concepts": found_concepts,
            "missing_concepts": missing_concepts,
        }

    # Single-topic or general queries:
    from CS2_PolicyLens.search import extract_salient_terms

    salient_words, phrases, quotes = extract_salient_terms(query)
    has_strong_evidence = False
    has_moderate_evidence = False

    for block in assembled_blocks:
        b_text = f"{block.get('section_heading', '')} {block.get('block_text', '')}".lower()
        score = block.get("retrieval_score", 0.0) or 0.0
        phrase_matches = [p for p in phrases if p in b_text]
        word_matches = [
            w for w in salient_words
            if w in b_text or (len(w) > 4 and (w[:4] in b_text or w.rstrip("sed") in b_text))
        ]

        if (phrase_matches or len(word_matches) >= 2) and score >= 0.35:
            has_strong_evidence = True
            break
        elif (word_matches or phrase_matches) and score >= 0.25:
            has_moderate_evidence = True

    if has_strong_evidence:
        status = "complete"
    elif has_moderate_evidence:
        status = "partial"
    else:
        status = "insufficient"

    return {
        "status": status,
        "target_concepts": [],
        "found_concepts": {},
        "missing_concepts": [],
    }


class RegulatoryQAEngine:
    """
    Robust RAG QA engine grounded in active regulatory vector indices with
    metadata filtering, adjacent expansion, and honest status semantics.
    """

    def __init__(
        self,
        collection_name: str = "policylens_structure",
        top_k: int = 4,
        min_score_threshold: float = 0.25,
        llm_client: Any | None = None,
        expand_adjacent: bool = True,
        max_expanded_hits: int = 2,
        include_predecessor: bool = True,
        include_successor: bool = True,
    ) -> None:
        self.collection_name = collection_name
        self.top_k = top_k
        self.min_score_threshold = min_score_threshold
        self.llm_client = llm_client
        self.expand_adjacent = expand_adjacent
        self.max_expanded_hits = max_expanded_hits
        self.include_predecessor = include_predecessor
        self.include_successor = include_successor

    def answer_question(
        self,
        query: str,
        collection_name: str | None = None,
        top_k: int | None = None,
        min_score_threshold: float | None = None,
        chroma_client: Any | None = None,
        embedding_engine: Any | None = None,
        registry_db_path: str | Path | None = None,
        use_hybrid: bool = False,
        use_rerank: bool = True,
        expand_adjacent: bool | None = None,
        max_expanded_hits: int | None = None,
        include_predecessor: bool | None = None,
        include_successor: bool | None = None,
        metadata_filter: str | dict[str, Any] | None = None,
        allowed_doc_ids: set[str] | Sequence[str] | None = None,
        manifest_meta: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Executes end-to-end grounded question answering:
        1. Resolve metadata filter (e.g. issuer=RBI) to constrain candidate retrieval.
        2. Retrieve top chunks strictly from active documents (dense or hybrid + Config 4).
        3. Formulate grounded prompt with adjacent context expansion and masthead denoising.
        4. Select contributing evidence blocks, pruning unrelated chunks.
        5. Evaluate evidence coverage (complete, partial, insufficient).
        6. Generate answer via injected LLM, Groq API, or structured extractive fallback.
        7. Return structured answer with exact citations and honest status semantics.
        """
        col = collection_name or self.collection_name
        k = top_k or self.top_k
        threshold = self.min_score_threshold if min_score_threshold is None else min_score_threshold

        # Guard: empty or whitespace query
        if not query or not query.strip():
            return {
                "question": query,
                "answer": "The available indexed regulatory documents do not provide sufficient evidence to answer this question. Please verify that the relevant circulars or master directions have been indexed.",
                "sources": [],
                "status": "insufficient_context",
                "llm_used": None,
                "collection": col,
                "filter_applied": str(metadata_filter) if metadata_filter else None,
            }

        # 1. Resolve and enforce metadata filter
        if allowed_doc_ids is None and metadata_filter is not None:
            try:
                allowed_doc_ids = resolve_allowed_document_ids(metadata_filter, manifest_meta)
            except ValueError as ve:
                return {
                    "question": query,
                    "answer": f"Invalid metadata filter '{metadata_filter}': {ve}",
                    "sources": [],
                    "status": "insufficient_evidence",
                    "llm_used": None,
                    "collection": col,
                    "filter_applied": str(metadata_filter),
                }

        if allowed_doc_ids is not None:
            allowed_doc_ids = set(allowed_doc_ids)
            if len(allowed_doc_ids) == 0:
                return {
                    "question": query,
                    "answer": f"The available indexed regulatory documents do not provide sufficient evidence to answer this question. No active documents match filter '{metadata_filter}'.",
                    "sources": [],
                    "status": "insufficient_evidence",
                    "llm_used": None,
                    "collection": col,
                    "filter_applied": str(metadata_filter),
                }

        # 2. Retrieve candidates strictly from active documents
        if use_hybrid and chroma_client is None:
            try:
                from CS2_PolicyLens.search import (
                    _load_manifest_metadata,
                    apply_lexical_rerank,
                    retrieve_hybrid_candidates,
                )

                if manifest_meta is None:
                    manifest_meta = _load_manifest_metadata()

                doc_filter = (
                    build_document_where_clause(allowed_doc_ids)
                    if allowed_doc_ids is not None
                    else None
                )
                raw_cands, _, _ = retrieve_hybrid_candidates(
                    query=query,
                    collection_name=col,
                    top_k_dense=max(k * 4, 20),
                    top_k_lexical=max(k * 4, 20),
                    active_doc_filter=doc_filter,
                    manifest_meta=manifest_meta,
                    allowed_doc_ids=allowed_doc_ids,
                )
                if use_rerank and raw_cands:
                    reranked = apply_lexical_rerank(raw_cands, query, manifest_meta=manifest_meta)
                    hits = reranked[:k]
                else:
                    hits = raw_cands[:k]
            except Exception as e:
                logger.warning("Hybrid candidate retrieval failed (%s); falling back to dense.", e)
                hits = query_policy_corpus(
                    query=query,
                    collection_name=col,
                    top_k=k,
                    chroma_client=chroma_client,
                    embedding_engine=embedding_engine,
                    registry_db_path=registry_db_path,
                    allowed_doc_ids=allowed_doc_ids,
                    metadata_filter=metadata_filter,
                )
        else:
            hits = query_policy_corpus(
                query=query,
                collection_name=col,
                top_k=k,
                chroma_client=chroma_client,
                embedding_engine=embedding_engine,
                registry_db_path=registry_db_path,
                allowed_doc_ids=allowed_doc_ids,
                metadata_filter=metadata_filter,
            )

        # Invariant check: strictly exclude any non-allowed document
        if allowed_doc_ids is not None:
            hits = [h for h in hits if h.get("document_id") in allowed_doc_ids]

        # 3. Check for sufficient context above threshold
        valid_hits = [h for h in hits if (h.get("score") is None or h["score"] >= threshold)]
        if not valid_hits:
            return {
                "question": query,
                "answer": "The available indexed regulatory documents do not provide sufficient evidence to answer this question. Please verify that the relevant circulars or master directions have been indexed.",
                "sources": [],
                "status": "insufficient_context",
                "llm_used": None,
                "collection": col,
                "filter_applied": str(metadata_filter) if metadata_filter else None,
            }

        # 4. Build structured evidence context and citations with bounded adjacent-chunk expansion
        context_parts: list[str] = []
        assembled_blocks: list[dict[str, Any]] = []
        consumed_chunk_ids: set[str] = set()

        do_expand = self.expand_adjacent if expand_adjacent is None else expand_adjacent
        max_expand = self.max_expanded_hits if max_expanded_hits is None else max_expanded_hits
        inc_pred = self.include_predecessor if include_predecessor is None else include_predecessor
        inc_succ = self.include_successor if include_successor is None else include_successor

        chroma_col = None
        if do_expand:
            try:
                from CS2_PolicyLens.src.indexing_pipeline import get_chroma_collection
                chroma_col = get_chroma_collection(col, chroma_client)
            except Exception as ce:
                logger.debug("Could not initialize Chroma collection for adjacent expansion: %s", ce)
                chroma_col = None

        source_idx = 1
        for hit_rank, hit in enumerate(valid_hits, 1):
            chunk_id = hit.get("chunk_id")
            if chunk_id and chunk_id in consumed_chunk_ids:
                continue

            doc_id = hit.get("document_id", "Unknown")
            primary_page = hit.get("page_number", 1)
            primary_section = hit.get("section_heading", "General Provisions")
            score = hit.get("score")
            primary_meta = hit.get("metadata") or {}
            primary_chunk_idx = primary_meta.get("chunk_index")
            if primary_chunk_idx is None and chunk_id:
                m_c = re.search(r"_(?:struct|fixed)_(\d+)$", chunk_id)
                if m_c:
                    try:
                        primary_chunk_idx = int(m_c.group(1))
                    except ValueError:
                        primary_chunk_idx = 0
            else:
                primary_chunk_idx = primary_chunk_idx if primary_chunk_idx is not None else 0

            primary_item = {
                "chunk_id": chunk_id or f"{doc_id}_{source_idx}",
                "document_id": doc_id,
                "chunk_index": primary_chunk_idx,
                "page_number": primary_page,
                "section_heading": primary_section,
                "text": hit.get("text", ""),
                "metadata": primary_meta,
                "is_expanded_neighbor": False,
            }

            block_chunks: list[dict[str, Any]] = [primary_item]
            if chunk_id:
                consumed_chunk_ids.add(chunk_id)

            # Selective adjacent expansion for top qualifying hits
            if do_expand and chroma_col is not None and (hit_rank <= max_expand):
                hit_text = hit.get("text", "")

                # Predecessor expansion
                sec_head = primary_section.lower()
                is_continuation = "continuation" in sec_head or "continued" in sec_head
                if inc_pred and (_starts_with_incomplete_sentence(hit_text) or is_continuation):
                    pred = _fetch_adjacent_chunk(
                        chroma_col, hit, direction=-1, allowed_doc_ids=allowed_doc_ids
                    )
                    if pred and pred["chunk_id"] not in consumed_chunk_ids:
                        block_chunks.append(pred)
                        consumed_chunk_ids.add(pred["chunk_id"])

                # Successor expansion
                if inc_succ and _ends_with_incomplete_sentence(hit_text):
                    succ = _fetch_adjacent_chunk(
                        chroma_col, hit, direction=+1, allowed_doc_ids=allowed_doc_ids
                    )
                    if succ and succ["chunk_id"] not in consumed_chunk_ids:
                        block_chunks.append(succ)
                        consumed_chunk_ids.add(succ["chunk_id"])

            def _safe_chunk_idx(item: dict[str, Any]) -> int:
                val = item.get("chunk_index")
                if val is None:
                    return 0
                try:
                    return int(val)
                except (ValueError, TypeError):
                    return 0

            block_chunks.sort(key=_safe_chunk_idx)

            constituent_ids = [c["chunk_id"] for c in block_chunks]
            raw_pages = []
            for c in block_chunks:
                p = c.get("page_number")
                if p is not None:
                    try:
                        raw_pages.append(int(p))
                    except (ValueError, TypeError):
                        pass
            page_numbers = sorted(list(set(raw_pages))) if raw_pages else [1]
            p_min, p_max = page_numbers[0], page_numbers[-1]
            page_span_str = f"{p_min}-{p_max}" if p_min != p_max else str(p_min)

            try:
                from CS2_PolicyLens.search import clean_masthead
            except Exception:
                def clean_masthead(t: str) -> str:
                    return t

            if len(block_chunks) > 1:
                chunk_snippets: list[str] = []
                for c in block_chunks:
                    c_txt = clean_masthead(c.get("text", "")).strip()
                    c_id = c["chunk_id"]
                    c_p = c.get("page_number", 1)
                    chunk_snippets.append(f"[Chunk: {c_id} | Page {c_p}]\n{c_txt}")
                block_body = "\n\n".join(chunk_snippets)
                header = (
                    f"[Source {source_idx} | Document: {doc_id} | Pages {page_span_str} "
                    f"| Chunks: {', '.join(constituent_ids)} | Section: {primary_section}]"
                )
            else:
                single_txt = clean_masthead(primary_item["text"]).strip()
                header = f"[Source {source_idx} | Document: {doc_id} | Page {p_min} | Section: {primary_section}]"
                block_body = single_txt

            context_parts.append(f"{header}\n{block_body}")
            assembled_blocks.append(
                {
                    "source_index": source_idx,
                    "document_id": doc_id,
                    "page_number": page_span_str if p_min != p_max else p_min,
                    "page_numbers": page_numbers,
                    "chunk_id": primary_item["chunk_id"],
                    "constituent_chunk_ids": constituent_ids,
                    "section_heading": primary_section,
                    "retrieval_score": score,
                    "block_text": block_body,
                    "header": header,
                }
            )
            source_idx += 1

        # 5. Evaluate evidence coverage
        target_concepts = extract_target_concepts(query)
        coverage_info = evaluate_evidence_coverage(query, assembled_blocks)
        cov_status = coverage_info.get("status", "insufficient")

        context_str = "\n\n---\n\n".join(context_parts)
        user_prompt = f"Regulatory Evidence Context:\n{context_str}\n\nQuestion: {query}\n\nAnswer:"

        # 6. Generate Answer via LLM or Extractive Fallback
        answer: str = ""
        model_used: str = "retrieval_only_fallback"
        final_status = "success"

        if self.llm_client is not None:
            # Custom injected LLM client (e.g. for deterministic mock testing)
            if hasattr(self.llm_client, "generate"):
                answer = self.llm_client.generate(SYSTEM_PROMPT, user_prompt)
            elif callable(self.llm_client):
                answer = self.llm_client(SYSTEM_PROMPT, user_prompt)
            else:
                raise TypeError("Injected llm_client must implement .generate() or be callable.")
            model_used = getattr(self.llm_client, "model_name", "injected_mock_llm")

            if "do not provide sufficient evidence" in answer or "insufficient evidence" in answer.lower():
                final_status = "insufficient_evidence"
            elif target_concepts and cov_status == "partial":
                final_status = "partial_evidence"
            else:
                final_status = "success"

        else:
            api_key = _load_groq_api_key()
            llm_success = False

            if api_key:
                try:
                    from groq import Groq

                    client = Groq(api_key=api_key)
                    candidate_models = [
                        "qwen/qwen3.8-27b",
                        "openai/gpt-oss-120b",
                        "llama-3.3-70b-versatile",
                        "llama-3.1-8b-instant",
                    ]
                    last_error = None
                    for model_name in candidate_models:
                        try:
                            response = client.chat.completions.create(
                                messages=[
                                    {"role": "system", "content": SYSTEM_PROMPT},
                                    {"role": "user", "content": user_prompt},
                                ],
                                model=model_name,
                                temperature=0.0,
                                max_tokens=650,
                            )
                            answer = response.choices[0].message.content or ""
                            model_used = f"groq/{model_name}"
                            llm_success = True
                            break
                        except Exception as me:
                            last_error = me
                            err_str = str(me).lower()
                            if (
                                "model_not_found" in err_str
                                or "404" in err_str
                                or "decommissioned" in err_str
                                or "not exist" in err_str
                                or "not have access" in err_str
                            ):
                                continue
                            raise

                    if not answer and last_error:
                        raise last_error

                except Exception as e:
                    logger.warning("Groq API call failed (%s); using extractive fallback.", e)
                    llm_success = False

            if llm_success and answer:
                if "do not provide sufficient evidence" in answer or "insufficient evidence" in answer.lower():
                    final_status = "insufficient_evidence"
                elif target_concepts and cov_status == "partial":
                    final_status = "partial_evidence"
                else:
                    final_status = "success"
            else:
                # Structured Extractive Fallback
                answer = self._generate_extractive_fallback(
                    coverage_info=coverage_info,
                    contributing_blocks=assembled_blocks,
                    query=query,
                )
                if target_concepts:
                    if cov_status == "complete":
                        final_status = "success"
                        model_used = "extractive_retrieval_fallback (offline/complete)"
                    elif cov_status == "partial":
                        final_status = "partial_evidence"
                        model_used = "extractive_retrieval_fallback (offline/partial)"
                    else:
                        final_status = "insufficient_evidence"
                        model_used = "extractive_retrieval_fallback (offline/insufficient)"
                else:
                    if cov_status == "complete":
                        final_status = "success"
                        model_used = "extractive_retrieval_fallback (offline/complete)"
                    elif cov_status == "partial":
                        final_status = "partial_evidence"
                        model_used = "extractive_retrieval_fallback (offline/partial)"
                    else:
                        final_status = "insufficient_evidence"
                        model_used = "extractive_retrieval_fallback (offline/insufficient)"

        # 7. Clean Source Attribution
        if final_status == "insufficient_evidence" and cov_status == "insufficient":
            clean_sources = []
        else:
            clean_sources = []
            for idx, src in enumerate(assembled_blocks, 1):
                clean_sources.append(
                    {
                        "source_index": idx,
                        "document_id": src["document_id"],
                        "page_number": src["page_number"],
                        "page_numbers": src["page_numbers"],
                        "chunk_id": src["chunk_id"],
                        "constituent_chunk_ids": src["constituent_chunk_ids"],
                        "section_heading": src["section_heading"],
                        "retrieval_score": src["retrieval_score"],
                    }
                )

        return {
            "question": query,
            "answer": answer.strip(),
            "sources": clean_sources,
            "status": final_status,
            "llm_used": model_used,
            "collection": col,
            "filter_applied": str(metadata_filter) if metadata_filter else None,
        }

    @staticmethod
    def _generate_extractive_fallback(
        coverage_info: dict[str, Any],
        contributing_blocks: Sequence[dict[str, Any]],
        query: str,
    ) -> str:
        """Constructs an honest, structured extractive summary grounded strictly in evidence."""
        status = coverage_info.get("status", "insufficient")
        target_concepts = coverage_info.get("target_concepts", [])
        found_concepts = coverage_info.get("found_concepts", {})
        missing_concepts = coverage_info.get("missing_concepts", [])

        # 1. Multi-concept queries (e.g. Clause 10 definitions)
        if target_concepts:
            lines = [
                "Extractive Regulatory Fallback (LLM API offline/unconfigured):",
                "The following regulatory provisions were extracted from verified active indices:",
                "",
            ]
            for concept in target_concepts:
                if concept in found_concepts:
                    info = found_concepts[concept]
                    lines.append(f"• {concept.title()}:")
                    lines.append(f"  \"{info['excerpt']}\"")
                    lines.append(
                        f"  [Source: {info['document_id']} | Page {info['page_number']} | Section: {info['section_heading']}]"
                    )
                    lines.append("")

            if missing_concepts:
                lines.append("[Unverified / Missing in Retrieved Context]:")
                for mc in missing_concepts:
                    lines.append(f"• {mc.title()}: Specific definition was not located in the retrieved page span.")
                lines.append("")

            return "\n".join(lines).strip()

        # 2. Single-topic or provision queries (e.g. Clause 8, pension compensation)
        if status == "insufficient" or not contributing_blocks:
            return (
                "The available indexed regulatory documents do not provide sufficient evidence to answer this question. "
                "Please verify that the relevant circulars or master directions have been indexed."
            )

        lines = [
            "Extractive Regulatory Fallback (LLM API offline/unconfigured):",
            "Relevant regulatory provisions retrieved from active verified indices:",
            "",
        ]
        for idx, block in enumerate(contributing_blocks[:2], 1):
            text_body = block.get("block_text", "").strip()
            # Clean section breadcrumbs
            cleaned_lines = [l for l in text_body.split("\n") if l.strip() and not l.startswith("[")]
            excerpt = " ".join(cleaned_lines)
            if len(excerpt) > 450:
                excerpt = excerpt[:447] + "..."
            lines.append(
                f"{idx}. [{block['document_id']} | Page {block['page_number']} | {block['section_heading']}]:\n   \"{excerpt}\""
            )
            lines.append("")

        if status == "partial":
            lines.append("[Note: Context provides partial evidence for this inquiry; secondary conditions may be unverified.]")

        return "\n".join(lines).strip()
