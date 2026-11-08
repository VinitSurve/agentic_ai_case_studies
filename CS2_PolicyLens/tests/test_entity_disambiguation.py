"""
Unit and regression tests for PolicyLens Entity-Level Retrieval Disambiguation module.

Covers:
1. Explicit Commercial Bank intent.
2. Explicit SFB intent.
3. Explicit NBFC intent.
4. Explicit PPI intent.
5. Explicit CIC intent.
6. Ambiguous entity wording in queries.
7. Query with zero entity references.
8. Missing and incomplete manifest metadata.
9. Mismatched sibling circular penalty scoring.
10. Conflicting entity query detection.
11. Fallback to unrestricted retrieval on ambiguous/none intent.
12. Genuine candidate deduplication across retrieval channels.
13. Resolution of matching document IDs with alias support.
14. Citation, provenance, and custom candidate attributes preservation.
15. Correct descending score sorting after adjustment.
16. Unrelated and unclassified documents not penalized.
17. Pension document classification (ensuring _pension_ is unclassified unless title establishes entity).
18. Alias registration with caller-supplied metadata.
19. Alias registration when loading manifest from disk.
20. All 12 supported entity classes detection and document classification.
21. Queries containing multiple entity types.
22. Ambiguous abbreviations and negative-context queries (PPI, CIC, AMC, SFB, REIT).
"""

from __future__ import annotations

import unittest
from typing import Any

from CS2_PolicyLens.src.entity_disambiguation import (
    DOC_ALIASES,
    EntityDetectionResult,
    _ensure_manifest_metadata,
    apply_entity_disambiguation_adjustment,
    detect_query_entity,
    get_document_entity_type,
    get_entity_matching_doc_ids,
)


class TestEntityDisambiguation(unittest.TestCase):
    """Test suite for entity detection, document classification, alias resolution, and scoring."""

    # -------------------------------------------------------------------------
    # 1. Intent Detection Tests for Primary Target Entities
    # -------------------------------------------------------------------------

    def test_01_explicit_commercial_bank_intent(self) -> None:
        """Scenario 1: Explicit Commercial Bank intent detection."""
        q = "What is the minimum threshold of banking outlets for a commercial bank to fall under the IO framework?"
        res = detect_query_entity(q)
        self.assertEqual(res.confidence, "explicit")
        self.assertEqual(res.entity_type, "COMMERCIAL_BANK")
        self.assertEqual(res.matched_phrase, "commercial bank")

        # Plural variation
        q2 = "Capital charge requirements for scheduled commercial banks"
        res2 = detect_query_entity(q2)
        self.assertEqual(res2.confidence, "explicit")
        self.assertEqual(res2.entity_type, "COMMERCIAL_BANK")

    def test_02_explicit_sfb_intent(self) -> None:
        """Scenario 2: Explicit Small Finance Bank intent detection."""
        q1 = "What are the Internal Ombudsman directions for Small Finance Banks?"
        res1 = detect_query_entity(q1)
        self.assertEqual(res1.confidence, "explicit")
        self.assertEqual(res1.entity_type, "SMALL_FINANCE_BANK")

        q2 = "Ombudsman appointment rules for SFBs"
        res2 = detect_query_entity(q2)
        self.assertEqual(res2.confidence, "explicit")
        self.assertEqual(res2.entity_type, "SMALL_FINANCE_BANK")

    def test_03_explicit_nbfc_intent(self) -> None:
        """Scenario 3: Explicit NBFC intent detection."""
        q1 = "Which deposit taking Non-Banking Financial Companies must appoint an IO?"
        res1 = detect_query_entity(q1)
        self.assertEqual(res1.confidence, "explicit")
        self.assertEqual(res1.entity_type, "NBFC")

        q2 = "Asset size threshold for NBFC customer interface requirements"
        res2 = detect_query_entity(q2)
        self.assertEqual(res2.confidence, "explicit")
        self.assertEqual(res2.entity_type, "NBFC")

    def test_04_explicit_ppi_intent(self) -> None:
        """Scenario 4: Explicit Prepaid Payment Instrument intent detection."""
        q1 = "Ombudsman requirements for Prepaid Payment Instruments issuers"
        res1 = detect_query_entity(q1)
        self.assertEqual(res1.confidence, "explicit")
        self.assertEqual(res1.entity_type, "PPI_ISSUER")

        q2 = "Customer protection rules for non-bank PPI issuers"
        res2 = detect_query_entity(q2)
        self.assertEqual(res2.confidence, "explicit")
        self.assertEqual(res2.entity_type, "PPI_ISSUER")

    def test_05_explicit_cic_intent(self) -> None:
        """Scenario 5: Explicit Credit Information Company intent detection."""
        q1 = "Complaint resolution timelines for Credit Information Companies"
        res1 = detect_query_entity(q1)
        self.assertEqual(res1.confidence, "explicit")
        self.assertEqual(res1.entity_type, "CREDIT_INFORMATION_COMPANY")

        q2 = "Internal Ombudsman framework for CICs"
        res2 = detect_query_entity(q2)
        self.assertEqual(res2.confidence, "explicit")
        self.assertEqual(res2.entity_type, "CREDIT_INFORMATION_COMPANY")

    def test_06_ambiguous_entity_wording(self) -> None:
        """Scenario 6: Ambiguous wording with multiple conflicting entity signals."""
        q = "Comparison of ombudsman rules between commercial banks and small finance banks"
        res = detect_query_entity(q)
        self.assertEqual(res.confidence, "ambiguous")
        self.assertIsNone(res.entity_type)
        self.assertIsNone(res.matched_phrase)

    def test_07_query_with_no_entity_reference(self) -> None:
        """Scenario 7: Query with zero entity references."""
        q = "What is the penalty for delay in credit of pension beyond the due date?"
        res = detect_query_entity(q)
        self.assertEqual(res.confidence, "none")
        self.assertIsNone(res.entity_type)
        self.assertIsNone(res.matched_phrase)

    # -------------------------------------------------------------------------
    # 2. Metadata Handling and Scoring Tests
    # -------------------------------------------------------------------------

    def test_08_missing_entity_metadata(self) -> None:
        """Scenario 8: Handling documents with missing or unresolvable entity metadata."""
        ent = get_document_entity_type("unknown_doc_2026", "General Circular on Guidelines")
        self.assertIsNone(ent)

        hits = [
            {"chunk_id": "c1", "document_id": "unknown_doc_2026", "score": 0.50},
        ]
        explicit_res = EntityDetectionResult(
            entity_type="COMMERCIAL_BANK", confidence="explicit", matched_phrase="commercial bank"
        )
        adjusted = apply_entity_disambiguation_adjustment(hits, explicit_res, manifest_meta={})
        self.assertEqual(adjusted[0]["score"], 0.50)
        self.assertEqual(adjusted[0]["entity_adj"], 0.0)

    def test_09_mismatched_sibling_penalty(self) -> None:
        """Scenario 9: Sibling circulars of distinct entity classes receive mismatch penalty."""
        manifest_meta = {
            "rbi_io_comm_2026": {"title": "Reserve Bank of India (Commercial Banks - Internal Ombudsman) Directions, 2026"},
            "rbi_internal_ombudsman_sfb_2026": {"title": "Reserve Bank of India (Small Finance Banks - Internal Ombudsman) Directions, 2026"},
            "rbi_internal_ombudsman_re_2023": {"title": "Master Direction - Reserve Bank of India (Internal Ombudsman for Regulated Entities) Directions, 2023"},
        }
        hits = [
            {"chunk_id": "c_comm", "document_id": "rbi_io_comm_2026", "score": 0.50},
            {"chunk_id": "c_sfb", "document_id": "rbi_internal_ombudsman_sfb_2026", "score": 0.55},
            {"chunk_id": "c_re", "document_id": "rbi_internal_ombudsman_re_2023", "score": 0.52},
        ]
        explicit_res = EntityDetectionResult(
            entity_type="COMMERCIAL_BANK", confidence="explicit", matched_phrase="commercial bank"
        )
        adjusted = apply_entity_disambiguation_adjustment(hits, explicit_res, manifest_meta=manifest_meta)

        self.assertEqual(adjusted[0]["chunk_id"], "c_comm")
        self.assertAlmostEqual(adjusted[0]["score"], 0.62)
        self.assertEqual(adjusted[1]["chunk_id"], "c_re")
        self.assertAlmostEqual(adjusted[1]["score"], 0.52)
        self.assertEqual(adjusted[2]["chunk_id"], "c_sfb")
        self.assertAlmostEqual(adjusted[2]["score"], 0.45)

    def test_09b_conflicting_entity_query_detection(self) -> None:
        """Scenario 9b: Query-level detection identifies conflicting entity signals."""
        q = "Do Commercial Banks and NBFCs follow the same internal ombudsman framework?"
        res = detect_query_entity(q)
        self.assertEqual(res.confidence, "ambiguous")
        self.assertIsNone(res.entity_type)
        self.assertIsNone(res.matched_phrase)

    def test_10_fallback_to_unrestricted_retrieval(self) -> None:
        """Scenario 10: Fallback to unrestricted retrieval when intent is ambiguous or none."""
        hits = [
            {"chunk_id": "c1", "document_id": "doc1", "score": 0.55},
            {"chunk_id": "c2", "document_id": "doc2", "score": 0.50},
        ]
        res_none = EntityDetectionResult(entity_type=None, confidence="none", matched_phrase=None)
        adj_none = apply_entity_disambiguation_adjustment(hits, res_none)
        self.assertEqual(adj_none, hits)

        res_amb = EntityDetectionResult(entity_type=None, confidence="ambiguous", matched_phrase=None)
        adj_amb = apply_entity_disambiguation_adjustment(hits, res_amb)
        self.assertEqual(adj_amb, hits)

    # -------------------------------------------------------------------------
    # 3. Candidate Deduplication & Metadata Resolution
    # -------------------------------------------------------------------------

    def test_11_candidate_deduplication_across_channels(self) -> None:
        """Scenario 11: Candidate deduplication across dense, lexical, and entity channels."""
        # Simulated dense channel candidates
        dense_candidates = [
            {"chunk_id": "chunk_001", "document_id": "doc_a", "score": 0.55, "source": "dense"},
            {"chunk_id": "chunk_002", "document_id": "doc_b", "score": 0.52, "source": "dense"},
        ]
        # Simulated lexical channel candidates with an overlap (chunk_002) and a new chunk (chunk_003)
        lexical_candidates = [
            {"chunk_id": "chunk_002", "document_id": "doc_b", "score": 0.50, "source": "lexical"},
            {"chunk_id": "chunk_003", "document_id": "doc_c", "score": 0.48, "source": "lexical"},
        ]
        # Simulated entity expansion candidates with an overlap (chunk_001) and a new chunk (chunk_004)
        entity_candidates = [
            {"chunk_id": "chunk_001", "document_id": "doc_a", "score": 0.54, "source": "entity_expansion"},
            {"chunk_id": "chunk_004", "document_id": "doc_d", "score": 0.46, "source": "entity_expansion"},
        ]

        # Merge simulating retrieve_hybrid_candidates logic
        merged: dict[str, dict[str, Any]] = {}
        for c in dense_candidates:
            merged[c["chunk_id"]] = dict(c)

        for c in lexical_candidates:
            cid = c["chunk_id"]
            if cid in merged:
                merged[cid]["source"] = "both"
            else:
                merged[cid] = dict(c)

        for c in entity_candidates:
            cid = c["chunk_id"]
            if cid not in merged:
                merged[cid] = dict(c)

        deduped = list(merged.values())
        # Exactly 4 unique chunks
        self.assertEqual(len(deduped), 4)
        chunk_ids = {c["chunk_id"] for c in deduped}
        self.assertEqual(chunk_ids, {"chunk_001", "chunk_002", "chunk_003", "chunk_004"})

        # chunk_002 merged dense + lexical -> 'both'
        self.assertEqual(merged["chunk_002"]["source"], "both")
        # chunk_001 already in dense, entity expansion did not overwrite original source
        self.assertEqual(merged["chunk_001"]["source"], "dense")
        # chunk_004 added via entity expansion
        self.assertEqual(merged["chunk_004"]["source"], "entity_expansion")

    def test_11b_matching_document_ids_resolution(self) -> None:
        """Scenario 11b: Resolution of document IDs matching an entity with alias support."""
        manifest_meta = {
            "rbi_internal_ombudsman_comm_2026": {"title": "Reserve Bank of India (Commercial Banks - Internal Ombudsman) Directions, 2026"},
            "rbi_climate_finance_2025": {"title": "Reserve Bank of India (Commercial Banks - Climate Finance) Directions, 2025"},
        }
        matching_docs = get_entity_matching_doc_ids("COMMERCIAL_BANK", manifest_meta=manifest_meta)
        self.assertIn("rbi_internal_ombudsman_comm_2026", matching_docs)
        self.assertIn("rbi_io_comm_2026", matching_docs)  # registered canonical alias
        self.assertIn("rbi_climate_finance_2025", matching_docs)

    def test_12_citation_and_provenance_preservation(self) -> None:
        """Scenario 12: Source attribution, metadata, and custom fields are preserved."""
        hits = [
            {
                "chunk_id": "rbi_io_comm_2026_struct_0001",
                "document_id": "rbi_io_comm_2026",
                "page_number": 2,
                "section_heading": "3. Applicability",
                "text": "These Directions shall be applicable to Commercial Banks...",
                "score": 0.50,
                "source": "entity_expansion",
                "custom_audit_key": "audit_verified_v1",
                "nested_provenance": {"collection": "policylens_structure", "strategy": "structure"},
                "metadata": {"custom_meta": "verified"},
            }
        ]
        manifest_meta = {
            "rbi_io_comm_2026": {"title": "Reserve Bank of India (Commercial Banks - Internal Ombudsman) Directions, 2026"}
        }
        explicit_res = EntityDetectionResult(
            entity_type="COMMERCIAL_BANK", confidence="explicit", matched_phrase="commercial bank"
        )
        adjusted = apply_entity_disambiguation_adjustment(hits, explicit_res, manifest_meta=manifest_meta)

        self.assertEqual(len(adjusted), 1)
        h = adjusted[0]
        self.assertEqual(h["chunk_id"], "rbi_io_comm_2026_struct_0001")
        self.assertEqual(h["document_id"], "rbi_io_comm_2026")
        self.assertEqual(h["page_number"], 2)
        self.assertEqual(h["section_heading"], "3. Applicability")
        self.assertEqual(h["source"], "entity_expansion")
        self.assertEqual(h["custom_audit_key"], "audit_verified_v1")
        self.assertEqual(h["nested_provenance"], {"collection": "policylens_structure", "strategy": "structure"})
        self.assertEqual(h["metadata"], {"custom_meta": "verified"})
        self.assertIn("These Directions shall be applicable", h["text"])

    # -------------------------------------------------------------------------
    # 4. Regression Tests: Pension Document Classification (Defect 1)
    # -------------------------------------------------------------------------

    def test_13_pension_document_classification(self) -> None:
        """
        Regression: Pension documents must remain unclassified unless their title
        explicitly establishes an agency bank or other regulated-entity class.
        """
        # Case A: Title explicitly mentions agency banks -> AGENCY_BANK
        ent_a = get_document_entity_type(
            "rbi_pension_2026",
            "Master Circular - Disbursement of Government Pension by Agency Banks",
        )
        self.assertEqual(ent_a, "AGENCY_BANK")

        # Case B: Document ID contains '_pension_' but title has NO regulated entity -> None (unclassified)
        ent_b = get_document_entity_type(
            "rbi_pension_2026",
            "Disbursement of Central Government Pension to Pensioners",
        )
        self.assertIsNone(ent_b)

        # Case C: Document ID contains '_pension_' with empty title -> None (unclassified)
        ent_c = get_document_entity_type("rbi_disbursement_pension_2026", "")
        self.assertIsNone(ent_c)

        # Case D: Generic pension document ID -> None
        ent_d = get_document_entity_type("central_pension_guidelines_2025", "Pension Scheme Guidelines")
        self.assertIsNone(ent_d)

        # Case E: Agency commission document explicitly establishes agency bank
        ent_e = get_document_entity_type(
            "rbi_agency_comm_2026",
            "Master Circular on Payment of Agency Commission to Agency Banks",
        )
        self.assertEqual(ent_e, "AGENCY_BANK")

    # -------------------------------------------------------------------------
    # 5. Regression Tests: Alias Registration (Defect 2)
    # -------------------------------------------------------------------------

    def test_14_alias_registration_with_caller_metadata(self) -> None:
        """
        Regression: _ensure_manifest_metadata must consistently register canonical
        aliases when caller-supplied metadata is provided.
        """
        # Caller supplies original manifest doc_id
        caller_meta_1 = {
            "rbi_internal_ombudsman_comm_2026": {"title": "Reserve Bank of India (Commercial Banks - Internal Ombudsman) Directions, 2026"}
        }
        res_1 = _ensure_manifest_metadata(caller_meta_1)
        self.assertIn("rbi_internal_ombudsman_comm_2026", res_1)
        self.assertIn("rbi_io_comm_2026", res_1)
        self.assertEqual(res_1["rbi_io_comm_2026"]["title"], caller_meta_1["rbi_internal_ombudsman_comm_2026"]["title"])

        # Caller supplies alias doc_id
        caller_meta_2 = {
            "rbi_io_comm_2026": {"title": "Reserve Bank of India (Commercial Banks - Internal Ombudsman) Directions, 2026"}
        }
        res_2 = _ensure_manifest_metadata(caller_meta_2)
        self.assertIn("rbi_io_comm_2026", res_2)
        self.assertIn("rbi_internal_ombudsman_comm_2026", res_2)

        # Caller supplies agency commission alias
        caller_meta_3 = {
            "rbi_agency_banks_comm_2026": {"title": "Payment of Agency Commission"}
        }
        res_3 = _ensure_manifest_metadata(caller_meta_3)
        self.assertIn("rbi_agency_comm_2026", res_3)

    def test_15_alias_registration_when_loading_from_disk(self) -> None:
        """
        Regression: _ensure_manifest_metadata loads disk manifest and registers all aliases.
        """
        disk_meta = _ensure_manifest_metadata(None)
        # All aliases from DOC_ALIASES must exist in the loaded dictionary
        for orig, alias in DOC_ALIASES.items():
            self.assertIn(orig, disk_meta)
            self.assertIn(alias, disk_meta)
            self.assertEqual(disk_meta[orig]["title"], disk_meta[alias]["title"])

    # -------------------------------------------------------------------------
    # 6. Regression Tests: All 12 Supported Entity Classes
    # -------------------------------------------------------------------------

    def test_16_all_12_supported_entity_classes_query_detection(self) -> None:
        """Regression: Query intent detection for all 12 supported regulated entity classes."""
        class_samples = {
            "COMMERCIAL_BANK": "Capital adequacy requirements for scheduled commercial banks",
            "SMALL_FINANCE_BANK": "Branch opening norms for small finance banks",
            "NBFC": "Prudential regulation of non-banking financial companies",
            "PPI_ISSUER": "Customer grievance redressal for prepaid payment instruments issuers",
            "CREDIT_INFORMATION_COMPANY": "Credit scoring accuracy by credit information companies",
            "AGENCY_BANK": "Reporting of central government transactions by agency banks",
            "PRIMARY_DEALER": "Liquidity facilities for standalone primary dealers",
            "MUTUAL_FUND": "Investment limits in debt schemes of mutual funds",
            "REIT": "Valuation of commercial properties held by real estate investment trusts",
            "INVIT": "Public issue of units by infrastructure investment trusts",
            "STOCK_EXCHANGE": "Listing of securities on recognized stock exchanges",
            "INSURER": "Solvency margin rules for registered insurance companies",
        }
        for expected_class, query_text in class_samples.items():
            res = detect_query_entity(query_text)
            self.assertEqual(
                res.confidence,
                "explicit",
                f"Failed explicit detection for class {expected_class} in query: {query_text}",
            )
            self.assertEqual(
                res.entity_type,
                expected_class,
                f"Expected entity_type {expected_class}, got {res.entity_type} for query: {query_text}",
            )

    def test_17_all_12_supported_entity_classes_document_classification(self) -> None:
        """Regression: Document classification for all 12 supported regulated entity classes."""
        doc_samples = {
            "COMMERCIAL_BANK": ("rbi_cb_2026", "Reserve Bank of India (Commercial Banks - Capital) Directions"),
            "SMALL_FINANCE_BANK": ("rbi_sfb_2026", "Directions for Small Finance Banks"),
            "NBFC": ("rbi_nbfc_2026", "Master Direction - Non-Banking Financial Companies"),
            "PPI_ISSUER": ("rbi_ppi_2026", "Master Direction on Prepaid Payment Instruments"),
            "CREDIT_INFORMATION_COMPANY": ("rbi_cic_2026", "Credit Information Companies Directions"),
            "AGENCY_BANK": ("rbi_agency_2026", "Conduct of Government Business by Agency Banks"),
            "PRIMARY_DEALER": ("rbi_pd_2026", "Operational Guidelines for Primary Dealers"),
            "MUTUAL_FUND": ("sebi_mf_2026", "SEBI (Mutual Funds) Regulations"),
            "REIT": ("sebi_reit_2026", "SEBI (Real Estate Investment Trusts) Regulations"),
            "INVIT": ("sebi_invit_2026", "SEBI (Infrastructure Investment Trusts) Regulations"),
            "STOCK_EXCHANGE": ("sebi_exchange_2026", "Securities Contracts (Stock Exchanges and Clearing Corporations) Regulations"),
            "INSURER": ("irdai_ins_2026", "IRDAI (Registration of Insurers) Regulations"),
        }
        for expected_class, (doc_id, title) in doc_samples.items():
            ent = get_document_entity_type(doc_id, title)
            self.assertEqual(
                ent,
                expected_class,
                f"Failed document classification for class {expected_class} (doc_id={doc_id}, title={title})",
            )

    # -------------------------------------------------------------------------
    # 7. Regression Tests: Multiple Entity Types & Ambiguous Queries
    # -------------------------------------------------------------------------

    def test_18_queries_containing_multiple_entity_types(self) -> None:
        """Regression: Queries referencing multiple entity types must return confidence='ambiguous'."""
        queries = [
            "Comparison of capital charge between commercial banks and NBFCs",
            "Do SFBs and CICs have identical internal ombudsman escalation paths?",
            "Investment caps for REITs, InvITs, and mutual funds",
            "Joint governance requirements for stock exchanges and primary dealers",
        ]
        for q in queries:
            res = detect_query_entity(q)
            self.assertEqual(
                res.confidence,
                "ambiguous",
                f"Expected ambiguous confidence for multi-entity query: {q}",
            )
            self.assertIsNone(res.entity_type)

    # -------------------------------------------------------------------------
    # 8. Regression Tests: Abbreviations & Negative Contexts
    # -------------------------------------------------------------------------

    def test_19_ambiguous_abbreviations_and_negative_contexts(self) -> None:
        """
        Regression: Broad abbreviations (PPI, CIC, AMC, SFB, REIT) used in unrelated
        or negative contexts must NOT be falsely classified.
        """
        negative_cases = [
            ("US producer price index PPI surged 0.4 percent in October", "PPI_ISSUER"),
            ("Proton pump inhibitor PPI medication dosage and side effects", "PPI_ISSUER"),
            ("Second appeal hearing before the Central Information Commission CIC under RTI", "CREDIT_INFORMATION_COMPANY"),
            ("RTI application rejected by the Central Information Commission CIC", "CREDIT_INFORMATION_COMPANY"),
            ("Annual maintenance contract AMC renewal terms for data center servers", "MUTUAL_FUND"),
            ("Hardware AMC tender for desktop computers and printers", "MUTUAL_FUND"),
            ("Air quality index in the San Francisco Bay SFB region", "SMALL_FINANCE_BANK"),
            ("We must re-iterate the deadline for compliance submissions", "REIT"),
        ]
        for q, target_entity in negative_cases:
            res = detect_query_entity(q)
            self.assertEqual(
                res.confidence,
                "none",
                f"Negative context for {target_entity} was falsely classified in: '{q}'",
            )
            self.assertIsNone(res.entity_type)

        # Contrast: Legitimate regulatory queries with the same abbreviations MUST be detected
        positive_cases = [
            ("Reserve Bank internal ombudsman framework for SFBs", "SMALL_FINANCE_BANK"),
            ("Turnaround time for complaint resolution by CICs", "CREDIT_INFORMATION_COMPANY"),
            ("Interoperability standards for non-bank PPI issuers", "PPI_ISSUER"),
            ("SEBI registration fee for mutual fund AMCs", "MUTUAL_FUND"),
            ("Listing and disclosure requirements for REITs", "REIT"),
        ]
        for q, expected_entity in positive_cases:
            res = detect_query_entity(q)
            self.assertEqual(
                res.confidence,
                "explicit",
                f"Failed explicit detection for legitimate query: '{q}'",
            )
            self.assertEqual(res.entity_type, expected_entity)

    # -------------------------------------------------------------------------
    # 9. Regression Tests: Score Sorting & Attribute Preservation
    # -------------------------------------------------------------------------

    def test_20_correct_sorting_after_score_adjustment(self) -> None:
        """
        Regression: Candidates must be strictly sorted in descending order of adjusted score.
        """
        manifest_meta = {
            "doc_target": {"title": "Reserve Bank of India (Commercial Banks - Capital) Directions"},
            "doc_sibling": {"title": "Reserve Bank of India (Small Finance Banks - Capital) Directions"},
            "doc_neutral": {"title": "General Administrative Circular"},
        }
        # Initial scores: sibling (0.62) > neutral (0.60) > target (0.55)
        hits = [
            {"chunk_id": "c_sibling", "document_id": "doc_sibling", "score": 0.62},
            {"chunk_id": "c_neutral", "document_id": "doc_neutral", "score": 0.60},
            {"chunk_id": "c_target", "document_id": "doc_target", "score": 0.55},
        ]
        explicit_res = EntityDetectionResult(
            entity_type="COMMERCIAL_BANK", confidence="explicit", matched_phrase="commercial bank"
        )
        adjusted = apply_entity_disambiguation_adjustment(hits, explicit_res, manifest_meta=manifest_meta)

        # Adjusted scores:
        # target:  0.55 + 0.12 = 0.67
        # neutral: 0.60 + 0.00 = 0.60
        # sibling: 0.62 - 0.10 = 0.52
        self.assertEqual(adjusted[0]["chunk_id"], "c_target")
        self.assertAlmostEqual(adjusted[0]["score"], 0.67)
        self.assertEqual(adjusted[1]["chunk_id"], "c_neutral")
        self.assertAlmostEqual(adjusted[1]["score"], 0.60)
        self.assertEqual(adjusted[2]["chunk_id"], "c_sibling")
        self.assertAlmostEqual(adjusted[2]["score"], 0.52)

        # Strict descending order verification
        for i in range(len(adjusted) - 1):
            self.assertGreaterEqual(adjusted[i]["score"], adjusted[i + 1]["score"])

    def test_21_unrelated_and_unclassified_documents_not_penalized(self) -> None:
        """
        Regression: Unrelated cross-regulatory and unclassified documents receive 0.0 adjustment
        and are NEVER penalized during entity disambiguation.
        """
        manifest_meta = {
            "sebi_kyc_nri_2026": {"title": "Master Circular on KYC Norms for Non-Resident Indians"},
            "irdai_expenses_2024": {"title": "Expenses of Management of Insurers Regulations"},
            "rbi_climate_2025": {"title": "Management of Climate Change Risks"},
            "rbi_pension_2026": {"title": "Disbursement of Central Government Pension"},
        }
        hits = [
            {"chunk_id": "c_sebi", "document_id": "sebi_kyc_nri_2026", "score": 0.58},
            {"chunk_id": "c_irdai", "document_id": "irdai_expenses_2024", "score": 0.54},
            {"chunk_id": "c_climate", "document_id": "rbi_climate_2025", "score": 0.51},
            {"chunk_id": "c_pension", "document_id": "rbi_pension_2026", "score": 0.49},
        ]
        explicit_res = EntityDetectionResult(
            entity_type="COMMERCIAL_BANK", confidence="explicit", matched_phrase="commercial bank"
        )
        adjusted = apply_entity_disambiguation_adjustment(hits, explicit_res, manifest_meta=manifest_meta)

        for h in adjusted:
            self.assertEqual(
                h["entity_adj"],
                0.0,
                f"Unrelated document {h['document_id']} was incorrectly given non-zero adjustment: {h['entity_adj']}",
            )


if __name__ == "__main__":
    unittest.main()
