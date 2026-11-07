"""
PolicyLens (Case Study 2) – Unit Tests for Search Ranking and Masthead Denoising

Validates:
1. Salient term and n-gram phrase extraction from queries.
2. Masthead and boilerplate removal from retrieval previews.
3. Lightweight lexical score boosting and rank reordering.
4. Non-destructive scoring behavior (base scores preserved, capped boost).
5. Baseline preservation when reranking is disabled.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch
from typing import Any

from CS2_PolicyLens.search import (
    DOMAIN_STOPWORDS,
    apply_lexical_rerank,
    clean_masthead,
    clean_preview_text,
    expand_query_text,
    extract_salient_terms,
    retrieve_hybrid_candidates,
)


class TestSearchRankingLogic(unittest.TestCase):
    def test_extract_salient_terms_standard_query(self) -> None:
        query = "When does a credit facility get classified as a non-performing asset or out of order?"
        salient_words, phrases, quotes = extract_salient_terms(query)

        # Salient words should include meaningful non-stopwords
        self.assertIn("credit", salient_words)
        self.assertIn("facility", salient_words)
        self.assertIn("classified", salient_words)
        self.assertIn("non-performing", salient_words)
        self.assertIn("asset", salient_words)

        # Stopwords must not appear in salient_words
        self.assertNotIn("when", salient_words)
        self.assertNotIn("does", salient_words)
        self.assertNotIn("or", salient_words)

        # Phrases should capture n-grams
        self.assertTrue(any("out of order" in p for p in phrases))
        self.assertTrue(any("credit facility" in p for p in phrases))

    def test_extract_salient_terms_with_quotes_and_dates(self) -> None:
        query = 'What is the circular reference number of the repealed instruction dated "14.10.2009"?'
        salient_words, phrases, quotes = extract_salient_terms(query)

        self.assertIn("14.10.2009", quotes)
        self.assertTrue(any("14.10.2009" in w for w in salient_words))
        self.assertIn("repealed", salient_words)
        # 'circular' is a generic domain stopword and must be excluded from single-word matches
        self.assertNotIn("circular", salient_words)

    def test_clean_masthead(self) -> None:
        dirty_text = (
            "Reserve Bank of India (Commercial Banks-Asset Classification, Provisioning and Income Recognition) Directions, 2026\n"
            "भारतीय ǐरजवर् बैंक\n"
            "__________________RESERVE BANK OF INDIA_________________\n"
            "An asset shall be classified as non-performing when it ceases to generate income."
        )
        cleaned = clean_masthead(dirty_text)

        self.assertNotIn("Reserve Bank of India (Commercial Banks-Asset Classification", cleaned)
        self.assertNotIn("भारतीय ǐरजवर् बैंक", cleaned)
        self.assertNotIn("__________________RESERVE BANK OF INDIA_________________", cleaned)
        self.assertIn("An asset shall be classified as non-performing when it ceases to generate income.", cleaned)

    def test_clean_preview_text(self) -> None:
        dirty_chunk = (
            "[rbi_asset_class_irac_2026 > Chapter V – Principles for Model Risk Management]\n\n"
            "भारतीय ǐरजवर् बैंक\n\n"
            "__________________RESERVE BANK OF INDIA_________________\n\n"
            "Reserve Bank of India (Internal Ombudsman for Commercial Banks) Directions, 2026\n\n"
            "Clause 10 states that banks having 10 or more outlets must appoint an Internal Ombudsman.\n"
        )
        preview = clean_preview_text(dirty_chunk, max_length=200)

        # Breadcrumb bracket must be stripped
        self.assertNotIn("[rbi_asset_class_irac_2026", preview)
        # Mastheads must be stripped
        self.assertNotIn("भारतीय ǐरजवर् बैंक", preview)
        self.assertNotIn("RESERVE BANK OF INDIA", preview)
        # Substantive text must remain
        self.assertIn("Clause 10 states that banks having 10 or more outlets", preview)
        self.assertLessEqual(len(preview), 200)

    def test_apply_lexical_rerank_promotes_relevant_chunk(self) -> None:
        query = "out of order credit facility non-performing asset"

        # Chunk A has high dense score but is generic / unrelated
        chunk_a = {
            "document_id": "generic_macro_doc",
            "page_number": 35,
            "score": 0.48,
            "text": "The monetary policy review indicates macroeconomic growth in credit disbursements.",
        }

        # Chunk B has lower dense score but exact statutory keywords
        chunk_b = {
            "document_id": "rbi_irac_statute",
            "page_number": 7,
            "score": 0.46,
            "text": "A credit facility is classified as out of order and non-performing asset when balance exceeds limit.",
        }

        hits = [chunk_a, chunk_b]

        # Prior to reranking, chunk_a is rank 1
        self.assertEqual(hits[0]["document_id"], "generic_macro_doc")

        # After reranking, chunk_b should be promoted to rank 1
        reranked = apply_lexical_rerank(hits, query, boost_weight=0.03)

        self.assertEqual(reranked[0]["document_id"], "rbi_irac_statute")
        self.assertGreater(reranked[0]["score"], reranked[1]["score"])
        # Original score preserved under base_score
        self.assertEqual(reranked[0]["base_score"], 0.46)
        self.assertGreater(reranked[0]["lexical_boost"], 0.0)

    def test_apply_lexical_rerank_preserves_order_on_zero_matches(self) -> None:
        query = "xylophone zebra quartz"
        chunk_1 = {"document_id": "doc1", "score": 0.60, "text": "Banking regulation on cash reserves."}
        chunk_2 = {"document_id": "doc2", "score": 0.40, "text": "Prudential limits on investment assets."}

        hits = [chunk_1, chunk_2]
        reranked = apply_lexical_rerank(hits, query)

        self.assertEqual(reranked[0]["document_id"], "doc1")
        self.assertEqual(reranked[1]["document_id"], "doc2")
        self.assertEqual(reranked[0]["lexical_boost"], 0.0)
        self.assertEqual(reranked[1]["lexical_boost"], 0.0)

    def test_apply_lexical_rerank_respects_max_boost_cap(self) -> None:
        query = "pension payment delay compensation interest rate bank guidelines circular"
        # Super-dense keyword text
        chunk = {
            "document_id": "dense_doc",
            "score": 0.30,
            "text": "pension payment delay compensation interest rate bank guidelines circular repeated multiple times.",
        }
        reranked = apply_lexical_rerank([chunk], query, max_boost=0.10)
        self.assertLessEqual(reranked[0]["lexical_boost"], 0.10)
        self.assertAlmostEqual(reranked[0]["score"], 0.40, places=4)

    def test_metadata_filtering_and_top_k_selection(self) -> None:
        hits = [
            {"document_id": "rbi_doc1", "issuer": "RBI", "score": 0.40, "text": "Asset classification norms for banks."},
            {"document_id": "sebi_doc1", "issuer": "SEBI", "score": 0.55, "text": "Securities investment norms for mutual funds."},
            {"document_id": "rbi_doc2", "issuer": "RBI", "score": 0.45, "text": "Non-performing assets and overdue credit."},
        ]
        # Filter for issuer == RBI
        rbi_hits = [h for h in hits if (h.get("issuer") or "").lower() == "rbi"]
        self.assertEqual(len(rbi_hits), 2)

        # Lexical reranking on filtered subset
        query = "non-performing assets overdue"
        reranked = apply_lexical_rerank(rbi_hits, query)
        top_1 = reranked[:1]
        self.assertEqual(len(top_1), 1)
        self.assertEqual(top_1[0]["document_id"], "rbi_doc2")

    def test_clean_preview_text_handles_empty_and_short_strings(self) -> None:
        self.assertEqual(clean_preview_text(""), "")
        self.assertEqual(clean_preview_text("   \n\n  "), "")
        self.assertEqual(clean_preview_text("Single line sentence."), "Single line sentence.")


class TestHybridCandidateGenerationAndMerging(unittest.TestCase):
    """
    Validates hybrid candidate generation, deduplication, metadata filtering,
    and punctuation/case handling.
    """

    def test_salient_terms_punctuation_and_domain_stopwords(self) -> None:
        query = 'Explain the "Internal Ombudsman" scheme under clause 8 of 2026 directions for banks with non-performing loans.'
        salient_words, phrases, quotes = extract_salient_terms(query)

        # Quotes captured accurately
        self.assertIn("internal ombudsman", quotes)

        # Domain stopwords must not appear in single-word list
        for stop in ["clause", "directions", "banks", "bank"]:
            self.assertNotIn(stop, salient_words)

        # Standalone digits must not appear
        self.assertNotIn("8", salient_words)
        self.assertNotIn("2026", salient_words)

        # Meaningful informative terms preserved
        self.assertIn("ombudsman", salient_words)
        self.assertIn("internal", salient_words)
        self.assertIn("loans", salient_words)
        self.assertIn("non-performing", salient_words)

    def test_expand_query_text_regulatory_acronyms(self) -> None:
        expanded_npa = expand_query_text("What is the norm for NPA?")
        self.assertIn("Non-Performing Asset", expanded_npa)

        expanded_io = expand_query_text("Appointment of IO in banks")
        self.assertIn("Internal Ombudsman", expanded_io)

        # Unrelated query not mutated
        normal_q = "What is the capital adequacy ratio?"
        self.assertEqual(expand_query_text(normal_q), normal_q)

    @patch("CS2_PolicyLens.search.get_chroma_collection")
    @patch("CS2_PolicyLens.search.get_database_connection")
    @patch("CS2_PolicyLens.src.embeddings.EmbeddingEngine")
    def test_retrieve_hybrid_candidates_merging_and_deduplication(
        self, mock_engine_cls: MagicMock, mock_db_conn: MagicMock, mock_get_col: MagicMock
    ) -> None:
        # Mock embedding engine
        mock_engine = MagicMock()
        mock_engine.encode.return_value = [[0.1] * 384]
        mock_engine_cls.return_value = mock_engine

        # Mock DB connection returning active fingerprints
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("fp_active_01",)]
        mock_conn.cursor.return_value = mock_cursor
        mock_db_conn.return_value = mock_conn

        # Mock ChromaDB collection
        mock_col = MagicMock()
        # Dense returns chunk_1 and chunk_2
        mock_col.query.return_value = {
            "ids": [["c1", "c2"]],
            "documents": [["Dense text 1", "Common text 2"]],
            "metadatas": [[{"document_id": "docA", "page_number": 1}, {"document_id": "docB", "page_number": 2}]],
            "distances": [[0.2, 0.4]],
        }
        # Lexical returns chunk_2 (overlap) and chunk_3 (lexical only)
        mock_col.get.return_value = {
            "ids": ["c2", "c3"],
            "documents": ["Common text 2", "Lexical text 3"],
            "metadatas": [{"document_id": "docB", "page_number": 2}, {"document_id": "docC", "page_number": 3}],
            "embeddings": [[0.1] * 384, [0.1] * 384],
        }
        mock_get_col.return_value = mock_col

        candidates, raw_pool, dedup_pool = retrieve_hybrid_candidates(
            query="non-performing asset classification",
            collection_name="policylens_structure",
            top_k_dense=2,
            top_k_lexical=2,
        )

        # Raw pool count is 2 (dense) + 2 (lexical) = 4
        self.assertEqual(raw_pool, 4)
        # Deduplicated pool has exactly 3 unique chunks (c1, c2, c3)
        self.assertEqual(dedup_pool, 3)
        self.assertEqual(len(candidates), 3)

        cand_map = {c["chunk_id"]: c for c in candidates}
        self.assertIn("c1", cand_map)
        self.assertIn("c2", cand_map)
        self.assertIn("c3", cand_map)

        # Source attribution checks
        self.assertEqual(cand_map["c1"]["source"], "dense")
        self.assertEqual(cand_map["c2"]["source"], "both")
        self.assertEqual(cand_map["c3"]["source"], "lexical")

        # Score checks: c1 score = 1.0 - 0.2 = 0.8
        self.assertAlmostEqual(cand_map["c1"]["score"], 0.8, places=2)

    @patch("CS2_PolicyLens.search.get_chroma_collection")
    @patch("CS2_PolicyLens.search.get_database_connection")
    @patch("CS2_PolicyLens.src.embeddings.EmbeddingEngine")
    def test_retrieve_hybrid_candidates_metadata_filter_propagation(
        self, mock_engine_cls: MagicMock, mock_db_conn: MagicMock, mock_get_col: MagicMock
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.encode.return_value = [[0.1] * 384]
        mock_engine_cls.return_value = mock_engine

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("fp_active_01",)]
        mock_conn.cursor.return_value = mock_cursor
        mock_db_conn.return_value = mock_conn

        mock_col = MagicMock()
        mock_col.query.return_value = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
        mock_col.get.return_value = {"ids": [], "documents": [], "metadatas": [], "embeddings": []}
        mock_get_col.return_value = mock_col

        active_filter = {"issuer": "RBI"}
        retrieve_hybrid_candidates(
            query="overdue loans",
            collection_name="policylens_structure",
            active_doc_filter=active_filter,
        )

        # Verify where filter in query call has the active_filter nested
        call_kwargs = mock_col.query.call_args[1]
        where_arg = call_kwargs["where"]
        self.assertIn("$and", where_arg)
        self.assertEqual(where_arg["$and"][1], {"issuer": "RBI"})

    def test_live_policylens_structure_hybrid_retrieval(self) -> None:
        # Live smoke test against indexed database policylens_structure
        query = "What are the asset classification norms for non-performing assets?"
        candidates, raw_pool, dedup_pool = retrieve_hybrid_candidates(
            query=query,
            collection_name="policylens_structure",
            top_k_dense=10,
            top_k_lexical=10,
        )
        self.assertGreater(len(candidates), 0)
        self.assertGreaterEqual(raw_pool, dedup_pool)
        for c in candidates:
            self.assertIn("chunk_id", c)
            self.assertIn("score", c)
            self.assertIn("source", c)
            self.assertIn(c["source"], ["dense", "lexical", "both"])


if __name__ == "__main__":
    unittest.main()
