"""
PolicyLens (Case Study 2) – Minimal RAG Question Answering Engine

Implements Phase 3.3 RAG Question Answering:
- Retrieves strictly from active documents via SQLite-isolated ChromaDB query.
- Formulates grounded prompts requiring strict adherence to regulatory evidence.
- Supports configurable local/cloud LLMs (Groq llama-3.3-70b-versatile) with automatic fallback.
- Guarantees complete provenance citations (document_id, page_number, section_heading, score).
- Returns an honest fallback when available evidence is insufficient.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Sequence

from CS2_PolicyLens.src.config import config
from CS2_PolicyLens.src.indexing_pipeline import query_policy_corpus

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
) -> dict[str, Any] | None:
    """
    Fetches and strictly validates an adjacent chunk from the same ChromaDB collection.

    Validation & Invariant Enforcement:
    1. direction must be -1 (predecessor) or +1 (successor).
    2. chunk_index must equal primary_index + direction exactly.
    3. document_id must match primary_hit.
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
    Note: Merely lacking a terminal period (e.g. table rows or section titles) is NOT
    sufficient to trigger successor expansion.
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


class RegulatoryQAEngine:
    """
    Minimal, robust RAG QA engine grounded in active regulatory vector indices.
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
    ) -> dict[str, Any]:
        """
        Executes end-to-end grounded question answering:
        1. Retrieve top chunks from active documents (supporting hybrid + Config 4).
        2. Filter by threshold / evidence presence.
        3. Formulate grounded prompt (with masthead denoising and adjacent context expansion).
        4. Call LLM (or execute extractive fallback if offline).
        5. Return answer with complete source citations.
        """
        col = collection_name or self.collection_name
        k = top_k or self.top_k
        threshold = self.min_score_threshold if min_score_threshold is None else min_score_threshold

        # 1. Retrieve strictly from active documents
        if use_hybrid and chroma_client is None:
            try:
                from CS2_PolicyLens.search import apply_lexical_rerank, retrieve_hybrid_candidates

                raw_cands, _, _ = retrieve_hybrid_candidates(
                    query=query,
                    collection_name=col,
                    top_k_dense=max(k * 4, 20),
                    top_k_lexical=max(k * 4, 20),
                )
                if use_rerank and raw_cands:
                    reranked = apply_lexical_rerank(raw_cands, query)
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
                )
        else:
            hits = query_policy_corpus(
                query=query,
                collection_name=col,
                top_k=k,
                chroma_client=chroma_client,
                embedding_engine=embedding_engine,
                registry_db_path=registry_db_path,
            )

        # 2. Check for sufficient context
        valid_hits = [h for h in hits if (h.get("score") is None or h["score"] >= threshold)]
        if not valid_hits:
            return {
                "question": query,
                "answer": "The available indexed regulatory documents do not provide sufficient evidence to answer this question. Please verify that the relevant circulars or master directions have been indexed.",
                "sources": [],
                "status": "insufficient_context",
                "llm_used": None,
                "collection": col,
            }

        # 3. Build structured evidence context and citations with bounded adjacent-chunk expansion
        context_parts: list[str] = []
        sources: list[dict[str, Any]] = []
        consumed_chunk_ids: set[str] = set()

        do_expand = self.expand_adjacent if expand_adjacent is None else expand_adjacent
        max_expand = self.max_expanded_hits if max_expanded_hits is None else max_expanded_hits
        inc_pred = self.include_predecessor if include_predecessor is None else include_predecessor
        inc_succ = self.include_successor if include_successor is None else include_successor

        # Get Chroma collection handle for neighbor lookups if expansion is requested
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
                # Already merged into a preceding adjacent-chunk context block
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

            # Perform selective adjacent expansion for top qualifying hits (bounded by max_expand)
            if do_expand and chroma_col is not None and (hit_rank <= max_expand):
                hit_text = hit.get("text", "")

                # 1. Immediate predecessor: fetch only when primary chunk starts with continuation / incomplete sentence
                if inc_pred and _starts_with_incomplete_sentence(hit_text):
                    pred = _fetch_adjacent_chunk(chroma_col, hit, direction=-1)
                    if pred and pred["chunk_id"] not in consumed_chunk_ids:
                        block_chunks.append(pred)
                        consumed_chunk_ids.add(pred["chunk_id"])

                # 2. Immediate successor: fetch only when primary chunk genuinely ends with an incomplete sentence
                if inc_succ and _ends_with_incomplete_sentence(hit_text):
                    succ = _fetch_adjacent_chunk(chroma_col, hit, direction=+1)
                    if succ and succ["chunk_id"] not in consumed_chunk_ids:
                        block_chunks.append(succ)
                        consumed_chunk_ids.add(succ["chunk_id"])

            # 3. Sort constituent chunks strictly in document reading order
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

            # Denoise repetitive regulatory circular running headers
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
            sources.append(
                {
                    "source_index": source_idx,
                    "document_id": doc_id,
                    "page_number": page_span_str if p_min != p_max else p_min,
                    "page_numbers": page_numbers,
                    "chunk_id": primary_item["chunk_id"],
                    "constituent_chunk_ids": constituent_ids,
                    "section_heading": primary_section,
                    "retrieval_score": score,
                }
            )
            source_idx += 1

        context_str = "\n\n---\n\n".join(context_parts)
        user_prompt = f"Regulatory Evidence Context:\n{context_str}\n\nQuestion: {query}\n\nAnswer:"

        # 4. Generate Answer via LLM or Extractive Fallback
        answer: str = ""
        model_used: str = "retrieval_only_fallback"

        if self.llm_client is not None:
            # Custom injected LLM client (e.g. for deterministic mock testing)
            if hasattr(self.llm_client, "generate"):
                answer = self.llm_client.generate(SYSTEM_PROMPT, user_prompt)
            elif callable(self.llm_client):
                answer = self.llm_client(SYSTEM_PROMPT, user_prompt)
            else:
                raise TypeError("Injected llm_client must implement .generate() or be callable.")
            model_used = getattr(self.llm_client, "model_name", "injected_mock_llm")
        else:
            # Try Groq API if key is available
            api_key = _load_groq_api_key()
            if api_key:
                try:
                    from groq import Groq

                    client = Groq(api_key=api_key)
                    # Support preferred models with fallbacks for endpoint differences
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
                                max_tokens=600,
                            )
                            answer = response.choices[0].message.content or ""
                            model_used = f"groq/{model_name}"
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
                    answer = self._generate_extractive_fallback(valid_hits, sources)
                    model_used = f"extractive_fallback (error: {e.__class__.__name__})"
            else:
                answer = self._generate_extractive_fallback(valid_hits, sources)
                model_used = "extractive_retrieval_fallback (no cloud API key)"

        return {
            "question": query,
            "answer": answer.strip(),
            "sources": sources,
            "status": "success",
            "llm_used": model_used,
            "collection": col,
        }

    @staticmethod
    def _generate_extractive_fallback(
        hits: Sequence[dict[str, Any]], sources: Sequence[dict[str, Any]]
    ) -> str:
        """Constructs an honest, grounded extractive summary when no LLM API is available."""
        lines = [
            "Extractive Regulatory Fallback (LLM API offline/unconfigured):",
            "Relevant regulatory provisions retrieved from active verified indices:",
            "",
        ]
        for idx, (hit, src) in enumerate(zip(hits[:3], sources[:3]), 1):
            excerpt = hit.get("text", "").replace("\n", " ")
            if len(excerpt) > 280:
                excerpt = excerpt[:280] + "..."
            lines.append(
                f"{idx}. [{src['document_id']} | Page {src['page_number']} | {src['section_heading']}]:\n   \"{excerpt}\""
            )
        return "\n".join(lines)
