"""
PolicyLens (Case Study 2) – Automated Unit Tests for Phase 3.3 Minimal RAG QA

Tests:
1. Grounded answer generation uses only retrieved active context (mock LLM receives exact context).
2. Source references are included with complete provenance (doc_id, page, section, score).
3. Insufficient context produces honest fallback without calling the LLM.
4. Inactive document chunks cannot leak into answer context.
5. Extractive fallback executes when cloud LLM API is unavailable/unconfigured.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from CS2_PolicyLens.src.embeddings import MockEmbeddingEngine
from CS2_PolicyLens.src.rag_qa import SYSTEM_PROMPT, RegulatoryQAEngine
from CS2_PolicyLens.src.version_registry import (
    get_database_connection,
    init_lifecycle_schema,
    promote_verified_candidate,
    reap_stalled_staging,
    register_staging_candidate,
    verify_staging_candidate,
    write_chunk_batch_guarded,
)
from CS2_PolicyLens.tests.test_indexing_pipeline import MockChromaClient


class MockLLM:
    """Mock LLM recorder for asserting grounded prompt formulation."""

    def __init__(self, response_text: str = "Mock answer based strictly on regulatory context.") -> None:
        self.response_text = response_text
        self.call_count = 0
        self.last_system_prompt: str | None = None
        self.last_user_prompt: str | None = None
        self.model_name = "test_mock_llm"

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.call_count += 1
        self.last_system_prompt = system_prompt
        self.last_user_prompt = user_prompt
        return self.response_text


class TestRegulatoryQAEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_policylens.db"
        self.conn = get_database_connection(self.db_path)
        init_lifecycle_schema(self.conn)

        self.chroma_client = MockChromaClient()
        self.embedding_engine = MockEmbeddingEngine(dimension=384)
        self.collection_name = "policylens_structure"

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def _seed_active_document(
        self,
        doc_id: str,
        fingerprint: str,
        version_id: str,
        chunks: list[dict[str, Any]],
    ) -> None:
        """Helper to seed active document records in SQLite and ChromaDB."""
        register_staging_candidate(
            conn=self.conn,
            document_id=doc_id,
            collection_name=self.collection_name,
            fingerprint=fingerprint,
            version_id=version_id,
            host_id="test_host",
            worker_id="worker_seed",
            pid=1234,
            process_start_time=100.0,
            lease_duration_seconds=300,
        )
        verify_staging_candidate(
            conn=self.conn,
            document_id=doc_id,
            collection_name=self.collection_name,
            fingerprint=fingerprint,
            worker_id="worker_seed",
            fencing_token=1,
            chunk_count=len(chunks),
            total_tokens=100,
        )
        promote_verified_candidate(
            conn=self.conn,
            document_id=doc_id,
            collection_name=self.collection_name,
            candidate_fingerprint=fingerprint,
            worker_id="worker_seed",
            fencing_token=1,
            chunk_count=len(chunks),
            total_tokens=100,
        )

        # ChromaDB chunks
        col = self.chroma_client.get_or_create_collection(self.collection_name)
        ids = [c["chunk_id"] for c in chunks]
        texts = [c["text"] for c in chunks]
        embeddings = self.embedding_engine.encode(texts)
        metadatas = [
            {
                "document_id": doc_id,
                "collection_name": self.collection_name,
                "index_fingerprint": fingerprint,
                "version_id": version_id,
                "page_number": c.get("page_number", 1),
                "section_heading": c.get("section_heading", "General"),
            }
            for c in chunks
        ]
        write_chunk_batch_guarded(
            chroma_collection=col,
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
            expected_doc_id=doc_id,
            expected_collection=self.collection_name,
            expected_fingerprint=fingerprint,
            expected_version_id=version_id,
        )

    def test_grounded_answer_generation_with_mock_llm(self) -> None:
        """
        Tests that QA engine retrieves active chunks, formulates strict grounded prompt,
        invokes the LLM with exact context, and produces structured answer with citations.
        """
        self._seed_active_document(
            doc_id="rbi_kyc_master_2024",
            fingerprint="fp_kyc_001",
            version_id="ver_001",
            chunks=[
                {
                    "chunk_id": "rbi_kyc_c1",
                    "text": "For High-Risk Customers, regulated entities must carry out periodic KYC updates once every 2 years.",
                    "page_number": 14,
                    "section_heading": "Periodic KYC Updating (Section 38)",
                }
            ],
        )

        mock_llm = MockLLM(
            response_text="According to Section 38 of rbi_kyc_master_2024, KYC updates for high-risk customers must be done every 2 years."
        )
        qa_engine = RegulatoryQAEngine(
            collection_name=self.collection_name,
            top_k=3,
            llm_client=mock_llm,
        )

        result = qa_engine.answer_question(
            query="How often must high-risk customer KYC be refreshed?",
            chroma_client=self.chroma_client,
            embedding_engine=self.embedding_engine,
            registry_db_path=self.db_path,
        )

        # 1. Verification of LLM call and prompt formulation
        self.assertEqual(mock_llm.call_count, 1)
        self.assertIn("STRICTLY grounded", mock_llm.last_system_prompt)
        self.assertIn("Never invent regulatory dates", mock_llm.last_system_prompt)

        # User prompt must contain the exact retrieved text, doc id, page, and section
        self.assertIn("rbi_kyc_master_2024", mock_llm.last_user_prompt)
        self.assertIn("Page 14", mock_llm.last_user_prompt)
        self.assertIn("Periodic KYC Updating (Section 38)", mock_llm.last_user_prompt)
        self.assertIn("once every 2 years", mock_llm.last_user_prompt)

        # 2. Result Verification
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["llm_used"], "test_mock_llm")
        self.assertIn("high-risk customers", result["answer"])

        # 3. Provenance Citations Verification
        self.assertEqual(len(result["sources"]), 1)
        src = result["sources"][0]
        self.assertEqual(src["document_id"], "rbi_kyc_master_2024")
        self.assertEqual(src["page_number"], 14)
        self.assertEqual(src["section_heading"], "Periodic KYC Updating (Section 38)")
        self.assertIsNotNone(src["retrieval_score"])

    def test_source_references_exact_structure(self) -> None:
        """
        Tests that all required source fields (document_id, page_number, section_heading, score)
        are populated across multiple retrieved chunks.
        """
        self._seed_active_document(
            doc_id="sebi_lodr_2025",
            fingerprint="fp_lodr_001",
            version_id="ver_lodr_1",
            chunks=[
                {
                    "chunk_id": "sebi_c1",
                    "text": "Regulation 29: Listed entities shall give prior intimation of board meetings at least 5 days in advance.",
                    "page_number": 42,
                    "section_heading": "Prior Intimations (Reg 29)",
                },
                {
                    "chunk_id": "sebi_c2",
                    "text": "Regulation 30: Disclosure of material events within 30 minutes of board closure.",
                    "page_number": 44,
                    "section_heading": "Material Events (Reg 30)",
                },
            ],
        )

        qa_engine = RegulatoryQAEngine(
            collection_name=self.collection_name,
            top_k=2,
            llm_client=MockLLM("Board meetings require 5 days notice."),
        )

        result = qa_engine.answer_question(
            query="What is the notice period for board meetings?",
            chroma_client=self.chroma_client,
            embedding_engine=self.embedding_engine,
            registry_db_path=self.db_path,
        )

        self.assertEqual(len(result["sources"]), 2)
        for idx, src in enumerate(result["sources"], 1):
            self.assertEqual(src["source_index"], idx)
            self.assertEqual(src["document_id"], "sebi_lodr_2025")
            self.assertIn(src["page_number"], (42, 44))
            self.assertTrue(src["section_heading"].startswith("Prior Intimations") or src["section_heading"].startswith("Material Events"))
            self.assertIsInstance(src["retrieval_score"], (float, int))

    def test_insufficient_context_honest_fallback_zero_llm_calls(self) -> None:
        """
        Tests that when no active documents exist or when chunks fall below the score threshold,
        the engine immediately returns the honest insufficient evidence fallback WITHOUT calling the LLM.
        """
        class BombLLM:
            def generate(self, *args: Any, **kwargs: Any) -> str:
                raise AssertionError("BombLLM should NEVER be called when context is insufficient!")

        qa_engine = RegulatoryQAEngine(
            collection_name=self.collection_name,
            llm_client=BombLLM(),
            min_score_threshold=0.5,
        )

        # 1. Empty database query
        result = qa_engine.answer_question(
            query="What are the capital adequacy ratios for small finance banks?",
            chroma_client=self.chroma_client,
            embedding_engine=self.embedding_engine,
            registry_db_path=self.db_path,
        )

        self.assertEqual(result["status"], "insufficient_context")
        self.assertIsNone(result["llm_used"])
        self.assertEqual(result["sources"], [])
        self.assertIn("do not provide sufficient evidence", result["answer"])

    def test_inactive_and_revoked_document_chunks_strictly_excluded(self) -> None:
        """
        Tests that chunks belonging to revoked, staging, or superseded versions
        CANNOT leak into the prompt context or source citations.
        """
        # 1. Seed active document
        self._seed_active_document(
            doc_id="active_pension_doc",
            fingerprint="fp_active_valid",
            version_id="ver_active_1",
            chunks=[
                {
                    "chunk_id": "active_c1",
                    "text": "Active rule: Recovery of excess pension requires prior pensioner notice.",
                    "page_number": 5,
                    "section_heading": "Pension Recovery Active",
                }
            ],
        )

        # 2. Seed revoked document into ChromaDB (not in document_registry, marked 'revoked' in lifecycle)
        register_staging_candidate(
            conn=self.conn,
            document_id="revoked_pension_doc",
            collection_name=self.collection_name,
            fingerprint="fp_revoked_dead",
            version_id="ver_revoked_99",
            worker_id="w_revoked",
            pid=1235,
            process_start_time=100.0,
            host_id="test_host",
            lease_duration_seconds=-10,  # expired
        )
        reap_stalled_staging(self.conn, "revoked_pension_doc", self.collection_name, "fp_revoked_dead")

        col = self.chroma_client.get_or_create_collection(self.collection_name)
        col.add(
            ids=["revoked_c1"],
            embeddings=self.embedding_engine.encode(["Revoked rule: Bank may arbitrarily seize pension with zero notice."]),
            documents=["Revoked rule: Bank may arbitrarily seize pension with zero notice."],
            metadatas=[
                {
                    "document_id": "revoked_pension_doc",
                    "collection_name": self.collection_name,
                    "index_fingerprint": "fp_revoked_dead",
                    "version_id": "ver_revoked_99",
                    "page_number": 99,
                    "section_heading": "Invalid Revoked Clause",
                }
            ],
        )

        mock_llm = MockLLM()
        qa_engine = RegulatoryQAEngine(
            collection_name=self.collection_name,
            llm_client=mock_llm,
        )

        result = qa_engine.answer_question(
            query="What are the notice rules for pension recovery?",
            chroma_client=self.chroma_client,
            embedding_engine=self.embedding_engine,
            registry_db_path=self.db_path,
        )

        # Active chunk is included
        self.assertEqual(result["status"], "success")
        self.assertIn("active_pension_doc", mock_llm.last_user_prompt)
        self.assertIn("prior pensioner notice", mock_llm.last_user_prompt)

        # Revoked chunk is strictly excluded
        self.assertNotIn("revoked_pension_doc", mock_llm.last_user_prompt)
        self.assertNotIn("arbitrarily seize", mock_llm.last_user_prompt)

        # Sources must only contain active document
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(result["sources"][0]["document_id"], "active_pension_doc")

    def test_extractive_fallback_when_offline_or_unconfigured(self) -> None:
        """
        Tests that when no cloud LLM API key is available and no custom LLM is injected,
        the engine cleanly produces an honest extractive fallback without crashing.
        """
        self._seed_active_document(
            doc_id="rbi_offline_guideline",
            fingerprint="fp_offline_01",
            version_id="ver_off_1",
            chunks=[
                {
                    "chunk_id": "off_c1",
                    "text": "Statutory Liquidity Ratio (SLR) is maintained at 18.0 percent of NDTL.",
                    "page_number": 2,
                    "section_heading": "SLR Requirements",
                }
            ],
        )

        qa_engine = RegulatoryQAEngine(
            collection_name=self.collection_name,
            llm_client=None,
        )

        # Mock _load_groq_api_key returning None (offline environment)
        with mock.patch("CS2_PolicyLens.src.rag_qa._load_groq_api_key", return_value=None):
            result = qa_engine.answer_question(
                query="What is the SLR requirement?",
                chroma_client=self.chroma_client,
                embedding_engine=self.embedding_engine,
                registry_db_path=self.db_path,
            )

        self.assertEqual(result["status"], "success")
        self.assertIn("extractive_retrieval_fallback", result["llm_used"])
        self.assertIn("Extractive Regulatory Fallback", result["answer"])
        self.assertIn("rbi_offline_guideline", result["answer"])
        self.assertIn("18.0 percent", result["answer"])
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(result["sources"][0]["document_id"], "rbi_offline_guideline")


if __name__ == "__main__":
    unittest.main()
