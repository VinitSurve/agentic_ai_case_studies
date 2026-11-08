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

    def test_rag_qa_context_assembly_denoises_mastheads(self) -> None:
        """
        Tests that repetitive regulatory circular mastheads are removed from prompt context
        so they do not pollute LLM token space.
        """
        self._seed_active_document(
            doc_id="rbi_masthead_test",
            fingerprint="fp_masthead_01",
            version_id="ver_mast_1",
            chunks=[
                {
                    "chunk_id": "mast_c1",
                    "text": (
                        "भारतीय ǐरजवर् बैंक\n"
                        "__________________RESERVE BANK OF INDIA_________________\n"
                        "Reserve Bank of India (Internal Ombudsman) Directions, 2026\n"
                        "Substantive rule: Commercial banks with 10 or more outlets must appoint an IO."
                    ),
                    "page_number": 2,
                    "section_heading": "Applicability",
                }
            ],
        )

        mock_llm = MockLLM()
        qa_engine = RegulatoryQAEngine(
            collection_name=self.collection_name,
            llm_client=mock_llm,
        )

        qa_engine.answer_question(
            query="What is the IO appointment threshold?",
            chroma_client=self.chroma_client,
            embedding_engine=self.embedding_engine,
            registry_db_path=self.db_path,
        )

        self.assertIsNotNone(mock_llm.last_user_prompt)
        prompt = mock_llm.last_user_prompt
        # Boilerplate mastheads should be stripped
        self.assertNotIn("भारतीय ǐरजवर् बैंक", prompt)
        self.assertNotIn("__________________RESERVE BANK OF INDIA_________________", prompt)
        # Substantive text must be preserved
        self.assertIn("Commercial banks with 10 or more outlets must appoint an IO.", prompt)

    def test_rag_qa_handles_empty_or_whitespace_query(self) -> None:
        """
        Tests graceful handling of empty or whitespace queries without exceptions.
        """
        qa_engine = RegulatoryQAEngine(collection_name=self.collection_name)
        result = qa_engine.answer_question(
            query="   ",
            chroma_client=self.chroma_client,
            embedding_engine=self.embedding_engine,
            registry_db_path=self.db_path,
        )
        self.assertEqual(result["status"], "insufficient_context")
        self.assertIn("do not provide sufficient evidence", result["answer"])
        self.assertEqual(result["sources"], [])

    @mock.patch("CS2_PolicyLens.search.apply_lexical_rerank")
    @mock.patch("CS2_PolicyLens.search.retrieve_hybrid_candidates")
    def test_rag_qa_hybrid_retrieval_mode(
        self, mock_retrieve_hybrid: mock.MagicMock, mock_apply_rerank: mock.MagicMock
    ) -> None:
        """
        Tests that use_hybrid=True invokes hybrid retrieval and Config 4 reranker.
        """
        mock_retrieve_hybrid.return_value = (
            [
                {
                    "chunk_id": "c_hyb_1",
                    "document_id": "doc_hyb",
                    "page_number": 7,
                    "section_heading": "Clause 8",
                    "text": "Non-performing assets criteria.",
                    "score": 0.65,
                }
            ],
            1,
            1,
        )
        mock_apply_rerank.return_value = [
            {
                "chunk_id": "c_hyb_1",
                "document_id": "doc_hyb",
                "page_number": 7,
                "section_heading": "Clause 8",
                "text": "Non-performing assets criteria.",
                "score": 0.70,
            }
        ]

        mock_llm = MockLLM()
        qa_engine = RegulatoryQAEngine(
            collection_name=self.collection_name,
            llm_client=mock_llm,
        )

        res = qa_engine.answer_question(
            query="What are NPA criteria?",
            use_hybrid=True,
            use_rerank=True,
        )

        self.assertEqual(res["status"], "success")
        self.assertTrue(mock_retrieve_hybrid.called)
        self.assertTrue(mock_apply_rerank.called)
        self.assertIn("Non-performing assets criteria", mock_llm.last_user_prompt)

    def test_clause_10_adjacent_chunk_expansion_reading_order_and_provenance(self) -> None:
        """
        Tests that adjacent expansion retrieves predecessor chunk 16 when chunk 17 is retrieved,
        preserves document reading order, exposes both chunk IDs, and cites the complete page span (Pages 15-16).
        """
        doc_id = "rbi_irac_test_doc"
        fp = "fp_irac_001"
        ver = "ver_irac_1"

        # Seed document with consecutive chunks 15, 16, 17, 18
        self._seed_active_document(
            doc_id=doc_id,
            fingerprint=fp,
            version_id=ver,
            chunks=[
                {
                    "chunk_id": f"{doc_id}_struct_0015",
                    "text": "Export project finance guidelines.",
                    "page_number": 14,
                    "section_heading": "Export Finance",
                },
                {
                    "chunk_id": f"{doc_id}_struct_0016",
                    "text": "10. Asset Classification Categories: (i) Sub-standard asset: An asset which has remained NPA for <= 12 months. (ii) Doubtful asset: An asset which has remained in the substandard",
                    "page_number": 15,
                    "section_heading": "(ii) Doubtful asset",
                },
                {
                    "chunk_id": f"{doc_id}_struct_0017",
                    "text": "category for 12 months. (iii) Loss asset: An asset where loss has been identified by the bank or RBI.",
                    "page_number": 16,
                    "section_heading": "Classification Details",
                },
                {
                    "chunk_id": f"{doc_id}_struct_0018",
                    "text": "11. Other Prudential Norms applicable to a bank.",
                    "page_number": 17,
                    "section_heading": "Prudential Norms",
                },
            ],
        )

        # Ensure chunk_index and metadata are populated on seeded records
        col = self.chroma_client.get_or_create_collection(self.collection_name)
        for idx in range(15, 19):
            cid = f"{doc_id}_struct_{idx:04d}"
            col.records[cid]["metadata"]["chunk_index"] = idx
            col.records[cid]["metadata"]["strategy"] = "structure_aware"

        mock_llm = MockLLM()
        qa_engine = RegulatoryQAEngine(
            collection_name=self.collection_name,
            llm_client=mock_llm,
            expand_adjacent=True,
            max_expanded_hits=1,
            include_predecessor=True,
            include_successor=False,
        )

        # Simulate retrieval that only returned chunk 17 (e.g. chunk 16 had low vector score)
        with mock.patch("CS2_PolicyLens.src.rag_qa.query_policy_corpus") as mock_query:
            mock_query.return_value = [
                {
                    "chunk_id": f"{doc_id}_struct_0017",
                    "document_id": doc_id,
                    "page_number": 16,
                    "section_heading": "Classification Details",
                    "text": "category for 12 months. (iii) Loss asset: An asset where loss has been identified by the bank or RBI.",
                    "score": 0.62,
                    "metadata": {
                        "document_id": doc_id,
                        "chunk_index": 17,
                        "version_id": ver,
                        "index_fingerprint": fp,
                        "collection_name": self.collection_name,
                        "page_number": 16,
                        "strategy": "structure_aware",
                    },
                }
            ]

            res = qa_engine.answer_question(
                query="What are the definitions of substandard asset, doubtful asset and loss asset under Clause 10?",
                chroma_client=self.chroma_client,
                embedding_engine=self.embedding_engine,
                registry_db_path=self.db_path,
            )

        self.assertEqual(res["status"], "success")
        prompt = mock_llm.last_user_prompt
        self.assertIsNotNone(prompt)

        # 1. Both chunks 0016 and 0017 must be present in prompt context
        self.assertIn(f"{doc_id}_struct_0016", prompt)
        self.assertIn(f"{doc_id}_struct_0017", prompt)

        # 2. Reading order preserved: chunk 16 appears before chunk 17
        idx_16 = prompt.index(f"{doc_id}_struct_0016")
        idx_17 = prompt.index(f"{doc_id}_struct_0017")
        self.assertLess(idx_16, idx_17)

        # 3. Context contains all three definitions: Sub-standard, Doubtful, and Loss
        self.assertIn("Sub-standard asset", prompt)
        self.assertIn("Doubtful asset", prompt)
        self.assertIn("Loss asset", prompt)

        # 4. Citation and provenance expose complete page span (Pages 15-16) and constituent chunk IDs
        self.assertEqual(len(res["sources"]), 1)
        src = res["sources"][0]
        self.assertEqual(src["document_id"], doc_id)
        self.assertEqual(src["page_number"], "15-16")
        self.assertEqual(src["page_numbers"], [15, 16])
        self.assertIn(f"{doc_id}_struct_0016", src["constituent_chunk_ids"])
        self.assertIn(f"{doc_id}_struct_0017", src["constituent_chunk_ids"])

    def test_adjacent_expansion_rejects_cross_document_boundary(self) -> None:
        """
        Tests that an adjacent chunk from a different document is strictly rejected
        and never leaks into the prompt context.
        """
        doc_a = "doc_alpha"
        doc_b = "doc_beta"

        self._seed_active_document(
            doc_id=doc_a,
            fingerprint="fp_a",
            version_id="ver_a",
            chunks=[
                {
                    "chunk_id": f"{doc_a}_struct_0001",
                    "text": "Doc Alpha Chunk 1 content.",
                    "page_number": 2,
                    "section_heading": "Alpha Section",
                }
            ],
        )
        self._seed_active_document(
            doc_id=doc_b,
            fingerprint="fp_b",
            version_id="ver_b",
            chunks=[
                {
                    "chunk_id": f"{doc_b}_struct_0000",
                    "text": "Doc Beta Chunk 0 content.",
                    "page_number": 1,
                    "section_heading": "Beta Section",
                }
            ],
        )

        col = self.chroma_client.get_or_create_collection(self.collection_name)
        col.records[f"{doc_a}_struct_0001"]["metadata"]["chunk_index"] = 1
        col.records[f"{doc_a}_struct_0001"]["metadata"]["strategy"] = "structure_aware"
        col.records[f"{doc_b}_struct_0000"]["metadata"]["chunk_index"] = 0
        col.records[f"{doc_b}_struct_0000"]["metadata"]["strategy"] = "structure_aware"

        mock_llm = MockLLM()
        qa_engine = RegulatoryQAEngine(
            collection_name=self.collection_name,
            llm_client=mock_llm,
            expand_adjacent=True,
        )

        with mock.patch("CS2_PolicyLens.src.rag_qa.query_policy_corpus") as mock_query:
            mock_query.return_value = [
                {
                    "chunk_id": f"{doc_a}_struct_0001",
                    "document_id": doc_a,
                    "page_number": 2,
                    "section_heading": "Alpha Section",
                    "text": "Doc Alpha Chunk 1 content.",
                    "score": 0.80,
                    "metadata": {
                        "document_id": doc_a,
                        "chunk_index": 1,
                        "version_id": "ver_a",
                        "index_fingerprint": "fp_a",
                        "collection_name": self.collection_name,
                        "page_number": 2,
                    },
                }
            ]

            res = qa_engine.answer_question(
                query="Query for Alpha",
                chroma_client=self.chroma_client,
                embedding_engine=self.embedding_engine,
                registry_db_path=self.db_path,
            )

        self.assertEqual(res["status"], "success")
        prompt = mock_llm.last_user_prompt
        self.assertNotIn(doc_b, prompt)
        self.assertNotIn("Doc Beta Chunk 0", prompt)
        self.assertEqual(res["sources"][0]["constituent_chunk_ids"], [f"{doc_a}_struct_0001"])

    def test_adjacent_expansion_rejects_mismatched_version_or_fingerprint(self) -> None:
        """
        Tests that candidate neighbor chunks with mismatched version_id or fingerprint
        (e.g., stale or superseded versions) are strictly rejected.
        """
        doc_id = "doc_version_check"
        active_ver = "ver_active_10"
        active_fp = "fp_active_10"

        # Seed active primary chunk
        self._seed_active_document(
            doc_id=doc_id,
            fingerprint=active_fp,
            version_id=active_ver,
            chunks=[
                {
                    "chunk_id": f"{doc_id}_struct_0001",
                    "text": "Active version content for chunk 1.",
                    "page_number": 2,
                    "section_heading": "Section Active",
                }
            ],
        )

        # Manually inject predecessor chunk 0 with stale version into Chroma collection
        col = self.chroma_client.get_or_create_collection(self.collection_name)
        col.records[f"{doc_id}_struct_0001"]["metadata"]["chunk_index"] = 1
        col.records[f"{doc_id}_struct_0001"]["metadata"]["strategy"] = "structure_aware"

        col.add(
            ids=[f"{doc_id}_struct_0000"],
            embeddings=self.embedding_engine.encode(["Stale predecessor content."]),
            documents=["Stale predecessor content."],
            metadatas=[
                {
                    "document_id": doc_id,
                    "collection_name": self.collection_name,
                    "index_fingerprint": "fp_stale_old",  # Mismatched fingerprint
                    "version_id": "ver_stale_old",        # Mismatched version_id
                    "chunk_index": 0,
                    "page_number": 1,
                    "section_heading": "Stale Section",
                }
            ],
        )

        mock_llm = MockLLM()
        qa_engine = RegulatoryQAEngine(
            collection_name=self.collection_name,
            llm_client=mock_llm,
            expand_adjacent=True,
        )

        with mock.patch("CS2_PolicyLens.src.rag_qa.query_policy_corpus") as mock_query:
            mock_query.return_value = [
                {
                    "chunk_id": f"{doc_id}_struct_0001",
                    "document_id": doc_id,
                    "page_number": 2,
                    "section_heading": "Section Active",
                    "text": "Active version content for chunk 1.",
                    "score": 0.85,
                    "metadata": {
                        "document_id": doc_id,
                        "chunk_index": 1,
                        "version_id": active_ver,
                        "index_fingerprint": active_fp,
                        "collection_name": self.collection_name,
                        "page_number": 2,
                    },
                }
            ]

            res = qa_engine.answer_question(
                query="Query for version check",
                chroma_client=self.chroma_client,
                embedding_engine=self.embedding_engine,
                registry_db_path=self.db_path,
            )

        self.assertEqual(res["status"], "success")
        prompt = mock_llm.last_user_prompt
        self.assertNotIn("Stale predecessor content", prompt)
        self.assertEqual(res["sources"][0]["constituent_chunk_ids"], [f"{doc_id}_struct_0001"])

    def test_adjacent_expansion_deduplicates_already_retrieved_neighbors(self) -> None:
        """
        Tests that when both a primary chunk and its neighbor were retrieved in the candidate pool,
        the neighbor is merged into the block and NOT duplicated in a second context block.
        """
        doc_id = "doc_dedup_test"
        fp = "fp_dedup_1"
        ver = "ver_dedup_1"

        self._seed_active_document(
            doc_id=doc_id,
            fingerprint=fp,
            version_id=ver,
            chunks=[
                {
                    "chunk_id": f"{doc_id}_struct_0005",
                    "text": "Chunk 5 text content.",
                    "page_number": 5,
                    "section_heading": "Section 5",
                },
                {
                    "chunk_id": f"{doc_id}_struct_0006",
                    "text": "continuation text of chunk 5.",
                    "page_number": 6,
                    "section_heading": "Section 6",
                },
            ],
        )

        col = self.chroma_client.get_or_create_collection(self.collection_name)
        col.records[f"{doc_id}_struct_0005"]["metadata"]["chunk_index"] = 5
        col.records[f"{doc_id}_struct_0005"]["metadata"]["strategy"] = "structure_aware"
        col.records[f"{doc_id}_struct_0006"]["metadata"]["chunk_index"] = 6
        col.records[f"{doc_id}_struct_0006"]["metadata"]["strategy"] = "structure_aware"

        mock_llm = MockLLM()
        qa_engine = RegulatoryQAEngine(
            collection_name=self.collection_name,
            llm_client=mock_llm,
            expand_adjacent=True,
            max_expanded_hits=2,
        )

        # Simulate retrieval where chunk 6 is rank 1 and chunk 5 is rank 2
        with mock.patch("CS2_PolicyLens.src.rag_qa.query_policy_corpus") as mock_query:
            mock_query.return_value = [
                {
                    "chunk_id": f"{doc_id}_struct_0006",
                    "document_id": doc_id,
                    "page_number": 6,
                    "section_heading": "Section 6",
                    "text": "continuation text of chunk 5.",
                    "score": 0.90,
                    "metadata": {
                        "document_id": doc_id,
                        "chunk_index": 6,
                        "version_id": ver,
                        "index_fingerprint": fp,
                        "collection_name": self.collection_name,
                        "page_number": 6,
                    },
                },
                {
                    "chunk_id": f"{doc_id}_struct_0005",
                    "document_id": doc_id,
                    "page_number": 5,
                    "section_heading": "Section 5",
                    "text": "Chunk 5 text content.",
                    "score": 0.70,
                    "metadata": {
                        "document_id": doc_id,
                        "chunk_index": 5,
                        "version_id": ver,
                        "index_fingerprint": fp,
                        "collection_name": self.collection_name,
                        "page_number": 5,
                    },
                },
            ]

            res = qa_engine.answer_question(
                query="Query for dedup",
                chroma_client=self.chroma_client,
                embedding_engine=self.embedding_engine,
                registry_db_path=self.db_path,
            )

        self.assertEqual(res["status"], "success")
        # Exactly 1 consolidated source block created; chunk 5 is NOT repeated as Source 2
        self.assertEqual(len(res["sources"]), 1)
        self.assertEqual(
            res["sources"][0]["constituent_chunk_ids"],
            [f"{doc_id}_struct_0005", f"{doc_id}_struct_0006"],
        )
        prompt = mock_llm.last_user_prompt
        self.assertEqual(prompt.count("[Source 1"), 1)
        self.assertEqual(prompt.count("[Source 2"), 0)

    def test_trailing_preposition_boundary_policy_and_clause_10_isolation(self) -> None:
        """
        Tests the selective boundary detector on trailing prepositions ('for', 'to', 'of', 'with'):
        1. Prepositions terminating headings, titles, or trailing sub-clauses (e.g. '...schema for',
           'Directions with respect to', 'Powers of') do NOT trigger false-positive successor expansion.
        2. Genuine incomplete sentences terminating with split punctuation (',', '—', '-') or
           coordinating conjunctions ('and', 'or') DO trigger expansion.
        3. Predecessors starting with lowercase continuations ('category for a period...') DO trigger expansion.
        4. Verifies that Chunk 17 ('...schema for') selectively fetches predecessor Chunk 16
           while strictly rejecting Chunk 18, ensuring Clause 10 remains isolated.
        """
        from CS2_PolicyLens.src.rag_qa import (
            _ends_with_incomplete_sentence,
            _starts_with_incomplete_sentence,
        )

        # 1. Prepositions terminating lines without punctuation must NOT trigger successor expansion
        self.assertFalse(_ends_with_incomplete_sentence("...schema for"))
        self.assertFalse(_ends_with_incomplete_sentence("Master Directions with respect to"))
        self.assertFalse(_ends_with_incomplete_sentence("Powers of"))
        self.assertFalse(_ends_with_incomplete_sentence("In accordance with"))
        self.assertFalse(_ends_with_incomplete_sentence("Risk weight for"))

        # 2. Genuine incomplete sentences terminating in split punctuation or conjunctions MUST trigger expansion
        self.assertTrue(_ends_with_incomplete_sentence("subject to the provisions of,"))
        self.assertTrue(_ends_with_incomplete_sentence("provided that the bank shall—"))
        self.assertTrue(_ends_with_incomplete_sentence("deficiencies are not corrected, and"))
        self.assertTrue(_ends_with_incomplete_sentence("under Clause 10("))
        self.assertTrue(_ends_with_incomplete_sentence("sub-standard assets re-"))

        # 3. Lowercase sentence continuation MUST trigger predecessor expansion
        self.assertTrue(_starts_with_incomplete_sentence("category for a period of twelve months."))
        self.assertTrue(_starts_with_incomplete_sentence("and shall be classified as non-performing."))
        self.assertFalse(_starts_with_incomplete_sentence("10. Asset classification categories."))
        self.assertFalse(_starts_with_incomplete_sentence("A bank shall ensure compliance."))

    def test_rbi_issuer_filtering_in_grounded_qa(self) -> None:
        """
        Tests that metadata_filter='issuer=RBI' constrains retrieval in grounded QA
        and prevents non-RBI documents (e.g. SEBI or DFS) from appearing in context or citations.
        """
        self._seed_active_document(
            doc_id="rbi_kyc_2026",
            fingerprint="fp_rbi_kyc",
            version_id="ver_rbi_1",
            chunks=[
                {
                    "chunk_id": "rbi_kyc_c1",
                    "text": "RBI KYC Directions require periodic update every 2 years for high risk.",
                    "page_number": 5,
                    "section_heading": "RBI Section",
                }
            ],
        )
        self._seed_active_document(
            doc_id="sebi_kyc_2026",
            fingerprint="fp_sebi_kyc",
            version_id="ver_sebi_1",
            chunks=[
                {
                    "chunk_id": "sebi_kyc_c1",
                    "text": "SEBI KYC Master Circular requires KRAs to upload records within 3 days.",
                    "page_number": 8,
                    "section_heading": "SEBI Section",
                }
            ],
        )

        manifest_mock = {
            "rbi_kyc_2026": {"issuer": "Reserve Bank of India (RBI)"},
            "sebi_kyc_2026": {"issuer": "Securities and Exchange Board of India (SEBI)"},
        }

        mock_llm = MockLLM()
        qa_engine = RegulatoryQAEngine(
            collection_name=self.collection_name,
            llm_client=mock_llm,
        )

        res = qa_engine.answer_question(
            query="What are KYC update requirements?",
            metadata_filter="issuer=RBI",
            chroma_client=self.chroma_client,
            embedding_engine=self.embedding_engine,
            registry_db_path=self.db_path,
            manifest_meta=manifest_mock,
        )

        self.assertEqual(res["status"], "success")
        self.assertIn("rbi_kyc_2026", mock_llm.last_user_prompt)
        self.assertNotIn("sebi_kyc_2026", mock_llm.last_user_prompt)
        self.assertEqual(len(res["sources"]), 1)
        self.assertEqual(res["sources"][0]["document_id"], "rbi_kyc_2026")

    def test_excluded_issuers_never_in_qa_context_or_citations(self) -> None:
        """
        Tests that when filtering for SEBI, RBI and DFS documents are strictly excluded.
        """
        self._seed_active_document(
            doc_id="sebi_inv_2026",
            fingerprint="fp_sebi",
            version_id="ver_sebi",
            chunks=[
                {"chunk_id": "sebi_c1", "text": "SEBI investor protection provisions.", "page_number": 2, "section_heading": "Investor Protection"}
            ],
        )
        self._seed_active_document(
            doc_id="rbi_inv_2026",
            fingerprint="fp_rbi",
            version_id="ver_rbi",
            chunks=[
                {"chunk_id": "rbi_c1", "text": "RBI investor grievance redressal.", "page_number": 3, "section_heading": "Grievance"}
            ],
        )
        self._seed_active_document(
            doc_id="dfs_nabfid_2026",
            fingerprint="fp_dfs",
            version_id="ver_dfs",
            chunks=[
                {"chunk_id": "dfs_c1", "text": "DFS NaBFID rules.", "page_number": 4, "section_heading": "NaBFID"}
            ],
        )

        manifest_mock = {
            "sebi_inv_2026": {"issuer": "Securities and Exchange Board of India (SEBI)"},
            "rbi_inv_2026": {"issuer": "Reserve Bank of India (RBI)"},
            "dfs_nabfid_2026": {"issuer": "Department of Financial Services, Ministry of Finance (DFS/GOI)"},
        }

        qa_engine = RegulatoryQAEngine(
            collection_name=self.collection_name,
            llm_client=MockLLM(),
        )
        res = qa_engine.answer_question(
            query="What are investor protections?",
            metadata_filter="issuer=SEBI",
            chroma_client=self.chroma_client,
            embedding_engine=self.embedding_engine,
            registry_db_path=self.db_path,
            manifest_meta=manifest_mock,
        )

        self.assertEqual(res["status"], "success")
        for src in res["sources"]:
            self.assertEqual(src["document_id"], "sebi_inv_2026")
            self.assertFalse(src["document_id"].startswith("rbi_"))
            self.assertFalse(src["document_id"].startswith("dfs_"))

    def test_clause_10_extractive_fallback_all_three_definitions_complete(self) -> None:
        """
        Tests that when Groq is unavailable, Clause 10 query extracts all three definitions
        (Substandard, Doubtful, Loss) from stitched chunks 16 and 17, returns status='success',
        and cites Pages 15-16.
        """
        doc_id = "rbi_irac_full_test"
        fp = "fp_irac_full"
        ver = "ver_irac_full"

        self._seed_active_document(
            doc_id=doc_id,
            fingerprint=fp,
            version_id=ver,
            chunks=[
                {
                    "chunk_id": f"{doc_id}_struct_0016",
                    "text": "10. Asset Classification Categories: (i) Sub-standard asset: An asset which has remained NPA for <= 12 months. (ii) Doubtful asset: An asset which has remained in the substandard",
                    "page_number": 15,
                    "section_heading": "(ii) Doubtful asset",
                },
                {
                    "chunk_id": f"{doc_id}_struct_0017",
                    "text": "category for 12 months. (iii) Loss asset: An asset where loss has been identified by the bank or RBI.",
                    "page_number": 16,
                    "section_heading": "Classification Details",
                },
            ],
        )

        col = self.chroma_client.get_or_create_collection(self.collection_name)
        col.records[f"{doc_id}_struct_0016"]["metadata"]["chunk_index"] = 16
        col.records[f"{doc_id}_struct_0016"]["metadata"]["strategy"] = "structure_aware"
        col.records[f"{doc_id}_struct_0017"]["metadata"]["chunk_index"] = 17
        col.records[f"{doc_id}_struct_0017"]["metadata"]["strategy"] = "structure_aware"

        qa_engine = RegulatoryQAEngine(
            collection_name=self.collection_name,
            llm_client=None,
            expand_adjacent=True,
            max_expanded_hits=1,
            include_predecessor=True,
        )

        with mock.patch("CS2_PolicyLens.src.rag_qa._load_groq_api_key", return_value=None):
            with mock.patch("CS2_PolicyLens.src.rag_qa.query_policy_corpus") as mock_query:
                mock_query.return_value = [
                    {
                        "chunk_id": f"{doc_id}_struct_0017",
                        "document_id": doc_id,
                        "page_number": 16,
                        "section_heading": "Classification Details",
                        "text": "category for 12 months. (iii) Loss asset: An asset where loss has been identified by the bank or RBI.",
                        "score": 0.65,
                        "metadata": {
                            "document_id": doc_id,
                            "chunk_index": 17,
                            "version_id": ver,
                            "index_fingerprint": fp,
                            "collection_name": self.collection_name,
                            "page_number": 16,
                            "strategy": "structure_aware",
                        },
                    }
                ]

                res = qa_engine.answer_question(
                    query="What are the definitions of substandard asset, doubtful asset and loss asset under Clause 10?",
                    chroma_client=self.chroma_client,
                    embedding_engine=self.embedding_engine,
                    registry_db_path=self.db_path,
                )

        self.assertEqual(res["status"], "success")
        self.assertIn("extractive_retrieval_fallback (offline/complete)", res["llm_used"])
        self.assertIn("Substandard Asset", res["answer"])
        self.assertIn("Doubtful Asset", res["answer"])
        self.assertIn("Loss Asset", res["answer"])
        self.assertEqual(res["sources"][0]["page_number"], "15-16")

    def test_clause_10_missing_substandard_reports_partial_evidence(self) -> None:
        """
        Tests that when only Doubtful and Loss assets are in context (chunk 16 is missing),
        the engine honestly reports status='partial_evidence' and marks Substandard as unverified.
        """
        doc_id = "rbi_irac_partial_test"
        fp = "fp_irac_part"
        ver = "ver_irac_part"

        self._seed_active_document(
            doc_id=doc_id,
            fingerprint=fp,
            version_id=ver,
            chunks=[
                {
                    "chunk_id": f"{doc_id}_struct_0017",
                    "text": "category for 12 months. A doubtful asset has weaknesses. (iii) Loss asset: An asset where loss has been identified by the bank or RBI.",
                    "page_number": 16,
                    "section_heading": "Classification Details",
                },
            ],
        )

        qa_engine = RegulatoryQAEngine(
            collection_name=self.collection_name,
            llm_client=None,
            expand_adjacent=False,
        )

        with mock.patch("CS2_PolicyLens.src.rag_qa._load_groq_api_key", return_value=None):
            with mock.patch("CS2_PolicyLens.src.rag_qa.query_policy_corpus") as mock_query:
                mock_query.return_value = [
                    {
                        "chunk_id": f"{doc_id}_struct_0017",
                        "document_id": doc_id,
                        "page_number": 16,
                        "section_heading": "Classification Details",
                        "text": "category for 12 months. A doubtful asset has weaknesses. (iii) Loss asset: An asset where loss has been identified by the bank or RBI.",
                        "score": 0.65,
                        "metadata": {
                            "document_id": doc_id,
                            "chunk_index": 17,
                            "version_id": ver,
                            "index_fingerprint": fp,
                            "collection_name": self.collection_name,
                            "page_number": 16,
                        },
                    }
                ]

                res = qa_engine.answer_question(
                    query="What are the definitions of substandard asset, doubtful asset and loss asset under Clause 10?",
                    chroma_client=self.chroma_client,
                    embedding_engine=self.embedding_engine,
                    registry_db_path=self.db_path,
                )

        self.assertEqual(res["status"], "partial_evidence")
        self.assertIn("extractive_retrieval_fallback (offline/partial)", res["llm_used"])
        self.assertIn("Doubtful Asset", res["answer"])
        self.assertIn("Loss Asset", res["answer"])
        self.assertIn("Unverified / Missing in Retrieved Context", res["answer"])
        self.assertIn("Substandard Asset", res["answer"])

    def test_clause_8_npa_retrieval_and_conditions_extractive(self) -> None:
        """
        Tests Clause 8 NPA classification conditions extraction across chunks 8 and 9.
        """
        doc_id = "rbi_irac_clause8_test"
        fp = "fp_c8"
        ver = "ver_c8"

        self._seed_active_document(
            doc_id=doc_id,
            fingerprint=fp,
            version_id=ver,
            chunks=[
                {
                    "chunk_id": f"{doc_id}_struct_0008",
                    "text": "8. A bank shall classify a financial asset as NPA if: (1) interest and/ or principal remains overdue for more than 90 days in respect of a term loan;",
                    "page_number": 9,
                    "section_heading": "8. Classification as Non-Performing Asset",
                },
                {
                    "chunk_id": f"{doc_id}_struct_0009",
                    "text": "(2) If it is classified as 'out of order' in respect of an Overdraft/ Cash Credit (OD/CC);",
                    "page_number": 10,
                    "section_heading": "Clause 8 Continuation",
                },
            ],
        )

        col = self.chroma_client.get_or_create_collection(self.collection_name)
        col.records[f"{doc_id}_struct_0008"]["metadata"]["chunk_index"] = 8
        col.records[f"{doc_id}_struct_0008"]["metadata"]["strategy"] = "structure_aware"
        col.records[f"{doc_id}_struct_0009"]["metadata"]["chunk_index"] = 9
        col.records[f"{doc_id}_struct_0009"]["metadata"]["strategy"] = "structure_aware"

        qa_engine = RegulatoryQAEngine(
            collection_name=self.collection_name,
            llm_client=None,
            expand_adjacent=True,
            include_predecessor=True,
        )

        with mock.patch("CS2_PolicyLens.src.rag_qa._load_groq_api_key", return_value=None):
            with mock.patch("CS2_PolicyLens.src.rag_qa.query_policy_corpus") as mock_query:
                mock_query.return_value = [
                    {
                        "chunk_id": f"{doc_id}_struct_0009",
                        "document_id": doc_id,
                        "page_number": 10,
                        "section_heading": "Clause 8 Continuation",
                        "text": "(2) If it is classified as 'out of order' in respect of an Overdraft/ Cash Credit (OD/CC);",
                        "score": 0.60,
                        "metadata": {
                            "document_id": doc_id,
                            "chunk_index": 9,
                            "version_id": ver,
                            "index_fingerprint": fp,
                            "collection_name": self.collection_name,
                            "page_number": 10,
                            "strategy": "structure_aware",
                        },
                    }
                ]

                res = qa_engine.answer_question(
                    query="What are the conditions for classifying an account as an NPA under Clause 8?",
                    chroma_client=self.chroma_client,
                    embedding_engine=self.embedding_engine,
                    registry_db_path=self.db_path,
                )

        self.assertEqual(res["status"], "success")
        self.assertIn("out of order", res["answer"])
        self.assertEqual(res["sources"][0]["page_number"], "9-10")

    def test_unsupported_filter_key_reports_error(self) -> None:
        """
        Tests that an unsupported filter key (e.g. unknown=foo) returns an honest error response.
        """
        qa_engine = RegulatoryQAEngine(collection_name=self.collection_name)
        res = qa_engine.answer_question(
            query="What is the SLR rate?",
            metadata_filter="unknown_key=foo",
            chroma_client=self.chroma_client,
            embedding_engine=self.embedding_engine,
            registry_db_path=self.db_path,
        )
        self.assertEqual(res["status"], "insufficient_evidence")
        self.assertIn("Invalid metadata filter", res["answer"])
        self.assertEqual(res["sources"], [])

    def test_empty_matching_filter_returns_honest_refusal(self) -> None:
        """
        Tests that a filter matching 0 documents returns honest refusal with status='insufficient_evidence'.
        """
        qa_engine = RegulatoryQAEngine(collection_name=self.collection_name)
        res = qa_engine.answer_question(
            query="What is the SLR rate?",
            metadata_filter="issuer=NONEXISTENT_ORG",
            chroma_client=self.chroma_client,
            embedding_engine=self.embedding_engine,
            registry_db_path=self.db_path,
        )
        self.assertEqual(res["status"], "insufficient_evidence")
        self.assertIn("No active documents match filter", res["answer"])
        self.assertEqual(res["sources"], [])


if __name__ == "__main__":
    unittest.main()
