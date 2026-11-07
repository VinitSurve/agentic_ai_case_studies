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
    ) -> None:
        self.collection_name = collection_name
        self.top_k = top_k
        self.min_score_threshold = min_score_threshold
        self.llm_client = llm_client

    def answer_question(
        self,
        query: str,
        collection_name: str | None = None,
        top_k: int | None = None,
        min_score_threshold: float | None = None,
        chroma_client: Any | None = None,
        embedding_engine: Any | None = None,
        registry_db_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """
        Executes end-to-end grounded question answering:
        1. Retrieve top chunks from active documents.
        2. Filter by threshold / evidence presence.
        3. Formulate grounded prompt.
        4. Call LLM (or execute extractive fallback if offline).
        5. Return answer with complete source citations.
        """
        col = collection_name or self.collection_name
        k = top_k or self.top_k
        threshold = self.min_score_threshold if min_score_threshold is None else min_score_threshold

        # 1. Retrieve strictly from active documents
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

        # 3. Build structured evidence context and citations
        context_parts: list[str] = []
        sources: list[dict[str, Any]] = []

        for idx, hit in enumerate(valid_hits, 1):
            doc_id = hit.get("document_id", "Unknown")
            page = hit.get("page_number", 1)
            section = hit.get("section_heading", "General Provisions")
            score = hit.get("score")
            text = hit.get("text", "").strip()

            context_parts.append(
                f"[Source {idx} | Document: {doc_id} | Page {page} | Section: {section}]\n{text}"
            )
            sources.append(
                {
                    "source_index": idx,
                    "document_id": doc_id,
                    "page_number": page,
                    "section_heading": section,
                    "retrieval_score": score,
                }
            )

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
                        "llama-3.3-70b-versatile",
                        "llama-3.1-70b-versatile",
                        "llama-3.1-8b-instant",
                        "qwen/qwen3.8-27b",
                        "openai/gpt-oss-120b",
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
