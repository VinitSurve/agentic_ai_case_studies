"""
PolicyLens (Case Study 2) – Unit & Integration Tests for Phase 3.2.1

Covers:
- Safe SQLite schema migration with rollback, FK integrity, and trigger re-creation.
- Database-enforced state transitions (rejecting direct illegal SQL updates).
- CAS-based candidate promotion and stale candidate rejection in two-candidate races.
- Worker identity and fencing token validation.
- Strict vector metadata validation against expected context (asserting zero ChromaDB calls).
- Active-only retrieval filtering and empty active registry behavior.
- Idempotent reconciliation sweeper and late-arriving write handling.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from CS2_PolicyLens.src.version_registry import (
    FencingRevokedError,
    LifecycleRegistryError,
    PromotionError,
    StalePromotionError,
    VectorMetadataMismatchError,
    check_worker_lease_and_fence,
    fail_revoked_version,
    get_database_connection,
    init_lifecycle_schema,
    migrate_lifecycle_schema,
    promote_verified_candidate,
    reap_stalled_staging,
    register_staging_candidate,
    retrieve_active_corpus,
    run_reconciliation_sweeper,
    validate_vector_batch_metadata,
    verify_staging_candidate,
    write_chunk_batch_guarded,
)


# =============================================================================
# High-Fidelity In-Memory Mock of ChromaDB Collection
# =============================================================================

class MockChromaCollection:
    """
    Mock conforming to the ChromaDB Collection API for isolated unit tests.
    """
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.add_call_count = 0
        self.query_call_count = 0
        self.delete_call_count = 0

    def add(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]]
    ) -> None:
        self.add_call_count += 1
        for i, emb, doc, meta in zip(ids, embeddings, documents, metadatas):
            self.records[i] = {
                "id": i,
                "embedding": emb,
                "document": doc,
                "metadata": dict(meta)
            }

    def delete(self, where: dict[str, Any] | None = None, ids: list[str] | None = None) -> None:
        self.delete_call_count += 1
        to_delete = []
        for i, rec in self.records.items():
            if ids and i in ids:
                to_delete.append(i)
            elif where and self._matches_filter(rec["metadata"], where):
                to_delete.append(i)
        for i in to_delete:
            del self.records[i]

    def query(
        self,
        query_embeddings: list[list[float]],
        n_results: int = 5,
        where: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.query_call_count += 1
        matching_ids = []
        matching_docs = []
        matching_metas = []
        matching_dists = []

        for _ in query_embeddings:
            q_ids, q_docs, q_metas, q_dists = [], [], [], []
            for rec in self.records.values():
                if where is None or self._matches_filter(rec["metadata"], where):
                    q_ids.append(rec["id"])
                    q_docs.append(rec["document"])
                    q_metas.append(rec["metadata"])
                    q_dists.append(0.05)
            matching_ids.append(q_ids[:n_results])
            matching_docs.append(q_docs[:n_results])
            matching_metas.append(q_metas[:n_results])
            matching_dists.append(q_dists[:n_results])

        return {
            "ids": matching_ids,
            "documents": matching_docs,
            "metadatas": matching_metas,
            "distances": matching_dists
        }

    def count(self, where: dict[str, Any] | None = None) -> int:
        if where is None:
            return len(self.records)
        return sum(1 for rec in self.records.values() if self._matches_filter(rec["metadata"], where))

    def _matches_filter(self, meta: dict[str, Any], where: dict[str, Any]) -> bool:
        if not where:
            return True
        if "$and" in where:
            return all(self._matches_filter(meta, sub) for sub in where["$and"])
        for k, v in where.items():
            if k == "$and":
                continue
            if isinstance(v, dict) and "$in" in v:
                if meta.get(k) not in v["$in"]:
                    return False
            else:
                if meta.get(k) != v:
                    return False
        return True


# =============================================================================
# Test Suite 1: SQLite Schema Migration & Transition Triggers
# =============================================================================

class TestSQLiteLifecycleMigration(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_migration.db"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_migration_preserves_records_foreign_keys_and_indexes(self) -> None:
        """
        Creates a legacy schema lacking 'revoked' state, seeds active and superseded
        records with a foreign key reference in document_registry, runs migration,
        and verifies all data, constraints, and 'revoked' support are intact.
        """
        conn = sqlite3.connect(str(self.db_path), isolation_level=None)
        conn.execute("PRAGMA foreign_keys = ON;")
        
        # 1. Setup legacy schema without 'revoked'
        conn.execute(
            """
            CREATE TABLE version_lifecycle (
                document_id TEXT NOT NULL,
                collection_name TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                version_id TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('staging', 'verified', 'active', 'superseded', 'failed')),
                host_id TEXT NOT NULL,
                worker_id TEXT NOT NULL,
                pid INTEGER NOT NULL,
                process_start_time REAL NOT NULL,
                fencing_token INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                lease_expires_at TEXT NOT NULL,
                chunk_count INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                validation_report_json TEXT,
                error_message TEXT,
                PRIMARY KEY (document_id, collection_name, fingerprint)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE document_registry (
                document_id TEXT NOT NULL,
                collection_name TEXT NOT NULL,
                active_fingerprint TEXT NOT NULL,
                active_version_id TEXT NOT NULL,
                chunk_count INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL,
                promoted_at TEXT NOT NULL,
                promoted_by TEXT NOT NULL,
                PRIMARY KEY (document_id, collection_name),
                FOREIGN KEY (document_id, collection_name, active_fingerprint) 
                    REFERENCES version_lifecycle(document_id, collection_name, fingerprint)
            );
            """
        )
        
        # 2. Insert pre-existing active and superseded records
        conn.execute(
            """
            INSERT INTO version_lifecycle VALUES 
            ('DOC_01', 'policylens_structure', 'fp_active_01', 'v1', 'active', 'host1', 'w1', 101, 1000.0, 1, '2026-01-01', '2026-01-01', '2026-01-01', 5, 1200, NULL, NULL),
            ('DOC_01', 'policylens_structure', 'fp_super_01',  'v0', 'superseded', 'host1', 'w0', 100, 900.0, 1, '2025-12-01', '2025-12-01', '2025-12-01', 5, 1200, NULL, NULL);
            """
        )
        conn.execute(
            """
            INSERT INTO document_registry VALUES 
            ('DOC_01', 'policylens_structure', 'fp_active_01', 'v1', 5, 1200, '2026-01-01', 'w1');
            """
        )
        conn.close()

        # 3. Execute migration
        migrate_lifecycle_schema(self.db_path)

        # 4. Verify post-migration integrity
        verify_conn = get_database_connection(self.db_path)
        
        # Verify row counts
        vl_count = verify_conn.execute("SELECT count(*) FROM version_lifecycle").fetchone()[0]
        dr_count = verify_conn.execute("SELECT count(*) FROM document_registry").fetchone()[0]
        self.assertEqual(vl_count, 2)
        self.assertEqual(dr_count, 1)

        # Verify insertion with state = 'revoked' succeeds
        verify_conn.execute(
            """
            INSERT INTO version_lifecycle VALUES 
            ('DOC_02', 'policylens_structure', 'fp_rev_02', 'v2', 'revoked', 'host1', 'w2', 102, 1100.0, 1, NULL, '2026-01-02', '2026-01-02', '2026-01-02', 0, 0, NULL, NULL);
            """
        )
        new_state = verify_conn.execute(
            "SELECT state FROM version_lifecycle WHERE fingerprint = 'fp_rev_02'"
        ).fetchone()[0]
        self.assertEqual(new_state, "revoked")

        # Verify foreign keys are active: deleting referenced version fails
        with self.assertRaises(sqlite3.IntegrityError):
            verify_conn.execute("DELETE FROM version_lifecycle WHERE fingerprint = 'fp_active_01'")

        verify_conn.close()

    def test_migration_rollback_on_failure(self) -> None:
        """
        Tests that if a foreign-key integrity failure is detected during migration,
        the transaction is rolled back and the original database remains intact.
        """
        conn = get_database_connection(self.db_path)
        init_lifecycle_schema(conn)
        conn.execute(
            """
            INSERT INTO version_lifecycle VALUES 
            ('DOC_ROLL', 'col', 'fp_init', 'v0', 'active', 'h', 'w', 1, 1.0, 1, NULL, '2026-01-01', '2026-01-01', '2026-01-01', 1, 100, NULL, NULL);
            """
        )
        # Corrupt foreign key relationship with PRAGMA foreign_keys = OFF
        conn.execute("PRAGMA foreign_keys = OFF;")
        conn.execute(
            """
            INSERT INTO document_registry VALUES 
            ('DOC_ROLL', 'col', 'fp_nonexistent_corrupt', 'v_bad', 1, 100, '2026-01-01', 'w');
            """
        )
        conn.close()

        # Attempt to migrate: PRAGMA foreign_key_check will detect the orphan registry row and rollback
        with self.assertRaises(RuntimeError) as ctx:
            migrate_lifecycle_schema(self.db_path)
        self.assertIn("Migration aborted and rolled back", str(ctx.exception))
        self.assertIn("Foreign key integrity check failed", str(ctx.exception))

        # Check that original database is preserved and untouched
        conn_after = get_database_connection(self.db_path)
        row = conn_after.execute("SELECT state FROM version_lifecycle WHERE fingerprint = 'fp_init'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "active")
        conn_after.close()

    def test_post_migration_trigger_enforces_legal_transitions(self) -> None:
        """
        Verifies that after migration, direct SQL statements attempting illegal transitions
        (e.g. revoked -> active, staging -> active) are aborted by the database trigger.
        """
        conn = get_database_connection(self.db_path)
        init_lifecycle_schema(conn)
        
        # 1. Staging -> Revoked (legal, using expired lease)
        register_staging_candidate(
            conn, "DOC_01", "policylens_structure", "fp_t1", "v1", "host1", "w1", 100, 1.0,
            lease_duration_seconds=-10
        )
        reap_success = reap_stalled_staging(conn, "DOC_01", "policylens_structure", "fp_t1")
        self.assertTrue(reap_success)
        state = conn.execute("SELECT state FROM version_lifecycle WHERE fingerprint = 'fp_t1'").fetchone()[0]
        self.assertEqual(state, "revoked")

        # 2. Direct SQL: revoked -> active (ILLEGAL)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            conn.execute("UPDATE version_lifecycle SET state = 'active' WHERE fingerprint = 'fp_t1'")
        self.assertIn("Illegal lifecycle state transition", str(ctx.exception))

        # 3. Direct SQL: revoked -> verified (ILLEGAL)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            conn.execute("UPDATE version_lifecycle SET state = 'verified' WHERE fingerprint = 'fp_t1'")
        self.assertIn("Illegal lifecycle state transition", str(ctx.exception))

        # 4. Direct SQL: revoked -> failed (LEGAL)
        fail_revoked_version(conn, "DOC_01", "policylens_structure", "fp_t1", "Purged after drain")
        final_state = conn.execute("SELECT state FROM version_lifecycle WHERE fingerprint = 'fp_t1'").fetchone()[0]
        self.assertEqual(final_state, "failed")

        # 5. Direct SQL: failed -> active (ILLEGAL)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            conn.execute("UPDATE version_lifecycle SET state = 'active' WHERE fingerprint = 'fp_t1'")
        self.assertIn("Illegal lifecycle state transition", str(ctx.exception))

        conn.close()


# =============================================================================
# Test Suite 2: CAS Candidate Promotion & Stale Race Detection
# =============================================================================

class TestCASCandidatePromotion(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_cas.db"
        self.conn = get_database_connection(self.db_path)
        init_lifecycle_schema(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def test_cas_promotion_success_from_scratch(self) -> None:
        """
        Tests promoting the very first version of a document (expected_active_fingerprint = None).
        """
        doc_id = "DOC_01"
        coll = "policylens_structure"
        fp = "fp_v1"
        worker_id = "worker_1"
        version_id = "v1"

        expected_fp = register_staging_candidate(
            self.conn, doc_id, coll, fp, version_id, "host1", worker_id, 100, 1.0
        )
        self.assertIsNone(expected_fp)

        # Verify staging candidate
        verify_staging_candidate(self.conn, doc_id, coll, fp, worker_id, 1, 10, 500)

        # Promote verified candidate
        res = promote_verified_candidate(self.conn, doc_id, coll, fp, worker_id, 1)
        self.assertEqual(res["status"], "promoted")
        self.assertEqual(res["active_fingerprint"], fp)

        # Confirm document_registry points to fp_v1
        reg_row = self.conn.execute("SELECT active_fingerprint, active_version_id FROM document_registry").fetchone()
        self.assertEqual(reg_row[0], fp)
        self.assertEqual(reg_row[1], version_id)

    def test_stale_candidate_rejected_in_two_candidate_race(self) -> None:
        """
        Two-candidate race:
        - Base version V0 is currently active.
        - Candidate 1 (C1) and Candidate 2 (C2) both register staging while V0 is active.
        - Both persist expected_active_fingerprint = fp_v0.
        - C2 verifies and promotes first -> becomes active.
        - C1 verifies and attempts promotion with persisted expected_active_fingerprint = fp_v0.
        - C1 is rejected with StalePromotionError.
        - Active registry remains C2; C1 remains verified and unpromoted.
        """
        doc_id = "DOC_RACE"
        coll = "policylens_structure"

        # 1. Establish base version V0
        register_staging_candidate(self.conn, doc_id, coll, "fp_v0", "v0", "host0", "w0", 100, 1.0)
        verify_staging_candidate(self.conn, doc_id, coll, "fp_v0", "w0", 1, 10, 1000)
        promote_verified_candidate(self.conn, doc_id, coll, "fp_v0", "w0", 1)
        self.assertEqual(self.conn.execute("SELECT active_fingerprint FROM document_registry").fetchone()[0], "fp_v0")

        # 2. Candidate 1 (C1) registers staging while V0 is active
        exp1 = register_staging_candidate(self.conn, doc_id, coll, "fp_c1", "c1", "host1", "w1", 101, 1.0)
        self.assertEqual(exp1, "fp_v0")
        verify_staging_candidate(self.conn, doc_id, coll, "fp_c1", "w1", 1, 12, 1200)

        # 3. Candidate 2 (C2) also registers staging while V0 is active
        exp2 = register_staging_candidate(self.conn, doc_id, coll, "fp_c2", "c2", "host2", "w2", 102, 1.0)
        self.assertEqual(exp2, "fp_v0")
        verify_staging_candidate(self.conn, doc_id, coll, "fp_c2", "w2", 1, 15, 1500)

        # 4. Candidate 2 promotes first -> succeeds!
        res_c2 = promote_verified_candidate(self.conn, doc_id, coll, "fp_c2", "w2", 1)
        self.assertEqual(res_c2["status"], "promoted")
        self.assertEqual(self.conn.execute("SELECT active_fingerprint FROM document_registry").fetchone()[0], "fp_c2")

        # 5. Candidate 1 attempts promotion -> rejected as stale!
        with self.assertRaises(StalePromotionError) as ctx:
            promote_verified_candidate(self.conn, doc_id, coll, "fp_c1", "w1", 1)
        self.assertIn("Stale candidate rejected", str(ctx.exception))
        self.assertIn("does not match persisted expected fingerprint 'fp_v0'", str(ctx.exception))

        # 6. Verify post-condition invariants
        # Registry still points to C2
        reg_active = self.conn.execute("SELECT active_fingerprint, active_version_id FROM document_registry").fetchone()
        self.assertEqual(reg_active[0], "fp_c2")
        self.assertEqual(reg_active[1], "c2")

        # C2 is 'active', C1 is 'verified' (unpromoted), V0 is 'superseded'
        s_c2 = self.conn.execute("SELECT state FROM version_lifecycle WHERE fingerprint = 'fp_c2'").fetchone()[0]
        s_c1 = self.conn.execute("SELECT state FROM version_lifecycle WHERE fingerprint = 'fp_c1'").fetchone()[0]
        s_v0 = self.conn.execute("SELECT state FROM version_lifecycle WHERE fingerprint = 'fp_v0'").fetchone()[0]
        self.assertEqual(s_c2, "active")
        self.assertEqual(s_c1, "verified")
        self.assertEqual(s_v0, "superseded")

    def test_promotion_rejected_on_worker_id_or_fencing_token_mismatch(self) -> None:
        """
        Tests that promotion is strictly conditional on matching worker_id and fencing_token.
        """
        doc_id = "DOC_FENCE"
        coll = "policylens_structure"
        fp = "fp_f1"

        register_staging_candidate(self.conn, doc_id, coll, fp, "v1", "host1", "w1", 100, 1.0, fencing_token=1)
        verify_staging_candidate(self.conn, doc_id, coll, fp, "w1", 1, 10, 500)

        # Worker ID mismatch
        with self.assertRaises(FencingRevokedError) as ctx:
            promote_verified_candidate(self.conn, doc_id, coll, fp, "imposter_worker", 1)
        self.assertIn("worker_id/fencing_token revoked", str(ctx.exception))

        # Fencing token mismatch
        with self.assertRaises(FencingRevokedError) as ctx:
            promote_verified_candidate(self.conn, doc_id, coll, fp, "w1", 999)
        self.assertIn("worker_id/fencing_token revoked", str(ctx.exception))

    def test_promotion_rejected_if_state_not_verified(self) -> None:
        """
        Tests that promotion cannot be executed directly from 'staging' state.
        """
        doc_id = "DOC_STG"
        coll = "policylens_structure"
        fp = "fp_stg"

        register_staging_candidate(self.conn, doc_id, coll, fp, "v1", "host1", "w1", 100, 1.0)
        # Attempt promotion while still in staging
        with self.assertRaises(PromotionError) as ctx:
            promote_verified_candidate(self.conn, doc_id, coll, fp, "w1", 1)
        self.assertIn("expected 'verified'", str(ctx.exception))

    def test_persisted_expected_fingerprint_behavior(self) -> None:
        """
        Tests that expected_active_fingerprint is persisted at staging registration
        and is NOT modified or derived dynamically at promotion time.
        """
        doc_id = "DOC_PERSIST"
        coll = "policylens_structure"

        # Step 1: Promote V0
        register_staging_candidate(self.conn, doc_id, coll, "fp_v0", "v0", "host0", "w0", 100, 1.0)
        verify_staging_candidate(self.conn, doc_id, coll, "fp_v0", "w0", 1, 10, 100)
        promote_verified_candidate(self.conn, doc_id, coll, "fp_v0", "w0", 1)

        # Step 2: Register V1 - expected_active_fingerprint should be persisted as fp_v0
        exp_fp = register_staging_candidate(self.conn, doc_id, coll, "fp_v1", "v1", "host1", "w1", 101, 1.0)
        self.assertEqual(exp_fp, "fp_v0")

        # Verify DB column explicitly
        row_before = self.conn.execute(
            "SELECT expected_active_fingerprint FROM version_lifecycle WHERE fingerprint = 'fp_v1'"
        ).fetchone()
        self.assertEqual(row_before[0], "fp_v0")

        # Step 3: Verify and promote V1
        verify_staging_candidate(self.conn, doc_id, coll, "fp_v1", "w1", 1, 12, 120)
        promote_verified_candidate(self.conn, doc_id, coll, "fp_v1", "w1", 1)

        # Verify that expected_active_fingerprint column in version_lifecycle was NOT overwritten
        row_after = self.conn.execute(
            "SELECT expected_active_fingerprint FROM version_lifecycle WHERE fingerprint = 'fp_v1'"
        ).fetchone()
        self.assertEqual(row_after[0], "fp_v0")

    def test_verification_rejected_on_worker_or_token_mismatch(self) -> None:
        """
        Tests that verify_staging_candidate raises FencingRevokedError if worker_id
        or fencing_token does not match.
        """
        doc_id = "DOC_VERIFY_MISMATCH"
        coll = "policylens_structure"
        fp = "fp_vm"

        register_staging_candidate(self.conn, doc_id, coll, fp, "v1", "host1", "w1", 100, 1.0, fencing_token=1)

        # Wrong worker_id
        with self.assertRaises(FencingRevokedError):
            verify_staging_candidate(self.conn, doc_id, coll, fp, "wrong_worker", 1, 10, 100)

        # Wrong fencing_token
        with self.assertRaises(FencingRevokedError):
            verify_staging_candidate(self.conn, doc_id, coll, fp, "w1", 99, 10, 100)

        # Correct worker and token succeeds
        verify_staging_candidate(self.conn, doc_id, coll, fp, "w1", 1, 10, 100)
        state = self.conn.execute("SELECT state FROM version_lifecycle WHERE fingerprint = ?", (fp,)).fetchone()[0]
        self.assertEqual(state, "verified")


# =============================================================================
# Test Suite 3: Strict Vector Metadata Validation
# =============================================================================

class TestStrictVectorMetadataValidation(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_chroma = MockChromaCollection()
        self.expected = {
            "expected_doc_id": "RBI_DOR_2023_01",
            "expected_collection": "policylens_structure",
            "expected_fingerprint": "fp_exact_12345",
            "expected_version_id": "v_exact_001"
        }
        self.valid_meta = {
            "document_id": "RBI_DOR_2023_01",
            "collection_name": "policylens_structure",
            "index_fingerprint": "fp_exact_12345",
            "version_id": "v_exact_001",
            "chunk_index": 0
        }

    def test_empty_expected_context_rejected_before_batch(self) -> None:
        """
        Tests that passing empty, whitespace, or non-string values for any expected
        context parameter raises VectorMetadataMismatchError before checking batch.
        """
        # Empty expected_doc_id
        with self.assertRaises(VectorMetadataMismatchError) as ctx:
            validate_vector_batch_metadata([self.valid_meta], "", "policylens_structure", "fp1", "v1")
        self.assertIn("Expected document_id cannot be empty", str(ctx.exception))

        # Empty expected_collection
        with self.assertRaises(VectorMetadataMismatchError) as ctx:
            validate_vector_batch_metadata([self.valid_meta], "DOC_1", "   ", "fp1", "v1")
        self.assertIn("Expected collection_name cannot be empty", str(ctx.exception))

        # Empty expected_fingerprint
        with self.assertRaises(VectorMetadataMismatchError) as ctx:
            validate_vector_batch_metadata([self.valid_meta], "DOC_1", "coll", "", "v1")
        self.assertIn("Expected index_fingerprint cannot be empty", str(ctx.exception))

        # Empty expected_version_id
        with self.assertRaises(VectorMetadataMismatchError) as ctx:
            validate_vector_batch_metadata([self.valid_meta], "DOC_1", "coll", "fp1", "  ")
        self.assertIn("Expected version_id cannot be empty", str(ctx.exception))

    def test_mismatched_document_id_blocks_chroma_add(self) -> None:
        bad_meta = dict(self.valid_meta, document_id="WRONG_DOC_ID")
        with self.assertRaises(VectorMetadataMismatchError) as ctx:
            write_chunk_batch_guarded(
                self.mock_chroma, ["id1"], [[0.1]*384], ["doc"], [bad_meta], **self.expected
            )
        self.assertIn("document_id 'WRONG_DOC_ID' != expected 'RBI_DOR_2023_01'", str(ctx.exception))
        self.assertEqual(self.mock_chroma.add_call_count, 0)

    def test_mismatched_collection_name_blocks_chroma_add(self) -> None:
        bad_meta = dict(self.valid_meta, collection_name="policylens_fixed")
        with self.assertRaises(VectorMetadataMismatchError) as ctx:
            write_chunk_batch_guarded(
                self.mock_chroma, ["id1"], [[0.1]*384], ["doc"], [bad_meta], **self.expected
            )
        self.assertIn("collection_name 'policylens_fixed' != expected 'policylens_structure'", str(ctx.exception))
        self.assertEqual(self.mock_chroma.add_call_count, 0)

    def test_mismatched_index_fingerprint_blocks_chroma_add(self) -> None:
        bad_meta = dict(self.valid_meta, index_fingerprint="fp_corrupted_999")
        with self.assertRaises(VectorMetadataMismatchError) as ctx:
            write_chunk_batch_guarded(
                self.mock_chroma, ["id1"], [[0.1]*384], ["doc"], [bad_meta], **self.expected
            )
        self.assertIn("index_fingerprint 'fp_corrupted_999' != expected 'fp_exact_12345'", str(ctx.exception))
        self.assertEqual(self.mock_chroma.add_call_count, 0)

    def test_mismatched_version_id_blocks_chroma_add(self) -> None:
        bad_meta = dict(self.valid_meta, version_id="v_foreign_version")
        with self.assertRaises(VectorMetadataMismatchError) as ctx:
            write_chunk_batch_guarded(
                self.mock_chroma, ["id1"], [[0.1]*384], ["doc"], [bad_meta], **self.expected
            )
        self.assertIn("version_id 'v_foreign_version' != expected 'v_exact_001'", str(ctx.exception))
        self.assertEqual(self.mock_chroma.add_call_count, 0)

    def test_valid_metadata_calls_chroma_add(self) -> None:
        write_chunk_batch_guarded(
            self.mock_chroma, ["id1"], [[0.1]*384], ["doc"], [self.valid_meta], **self.expected
        )
        self.assertEqual(self.mock_chroma.add_call_count, 1)
        self.assertEqual(self.mock_chroma.count(), 1)


# =============================================================================
# Test Suite 4: Retrieval Isolation & Reconciliation Sweeper
# =============================================================================

class TestRetrievalIsolationAndReconciliation(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_retrieval.db"
        self.conn = get_database_connection(self.db_path)
        init_lifecycle_schema(self.conn)
        self.mock_chroma = MockChromaCollection()

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def test_empty_active_registry_returns_empty_without_chroma_query(self) -> None:
        """
        When document_registry contains zero active fingerprints, retrieval returns
        an empty result dictionary immediately without querying ChromaDB.
        """
        res = retrieve_active_corpus(
            self.conn, self.mock_chroma, "policylens_structure", [[0.1]*384], top_k=5
        )
        self.assertEqual(len(res["ids"][0]), 0)
        self.assertEqual(len(res["documents"][0]), 0)
        self.assertEqual(self.mock_chroma.query_call_count, 0)

    def test_retrieval_strictly_filters_active_fingerprints(self) -> None:
        """
        Pre-seeds ChromaDB with vectors from:
        - Active version (fp_active)
        - Staging version (fp_staging)
        - Revoked version (fp_revoked)
        - Failed version (fp_failed)
        - Superseded version (fp_superseded)
        Verifies retrieval only returns vectors belonging to the active version.
        """
        doc_id = "DOC_01"
        coll = "policylens_structure"

        # Register and promote active version
        register_staging_candidate(self.conn, doc_id, coll, "fp_active", "v_act", "h1", "w1", 100, 1.0)
        verify_staging_candidate(self.conn, doc_id, coll, "fp_active", "w1", 1, 1, 100)
        promote_verified_candidate(self.conn, doc_id, coll, "fp_active", "w1", 1)

        # Seed ChromaDB
        all_metas = [
            {"document_id": doc_id, "collection_name": coll, "index_fingerprint": "fp_active", "version_id": "v_act"},
            {"document_id": doc_id, "collection_name": coll, "index_fingerprint": "fp_staging", "version_id": "v_stg"},
            {"document_id": doc_id, "collection_name": coll, "index_fingerprint": "fp_revoked", "version_id": "v_rev"},
            {"document_id": doc_id, "collection_name": coll, "index_fingerprint": "fp_failed", "version_id": "v_fail"},
            {"document_id": doc_id, "collection_name": coll, "index_fingerprint": "fp_superseded", "version_id": "v_sup"}
        ]
        self.mock_chroma.add(
            ids=["act_1", "stg_1", "rev_1", "fail_1", "sup_1"],
            embeddings=[[0.1]*384] * 5,
            documents=["Active text", "Staging text", "Revoked text", "Failed text", "Superseded text"],
            metadatas=all_metas
        )
        self.assertEqual(self.mock_chroma.count(), 5)

        # Retrieve active corpus
        res = retrieve_active_corpus(
            self.conn, self.mock_chroma, coll, [[0.1]*384], top_k=10
        )
        retrieved_ids = res["ids"][0]
        self.assertEqual(len(retrieved_ids), 1)
        self.assertEqual(retrieved_ids[0], "act_1")
        self.assertEqual(res["documents"][0][0], "Active text")

    def test_late_write_reconciliation_and_sweeper_idempotency(self) -> None:
        """
        Full lifecycle test:
        1. Version V1 fails and initial purge runs.
        2. Late write arrives in ChromaDB for V1.
        3. Retrieval query verifies V1 is completely excluded.
        4. Scheduled reconciliation sweeper discovers and purges V1 vectors.
        5. ChromaDB count for V1 is 0.
        6. Repeated sweep runs: deletes 0, raises no error (idempotent).
        7. Final retrieval check remains isolated and clean.
        """
        doc_id = "DOC_RECON"
        coll = "policylens_structure"
        fp_failed = "fp_failed_v1"
        ver_failed = "v_failed_1"

        # 1. Register staging with expired lease, then revoke and mark failed in SQLite
        register_staging_candidate(
            self.conn, doc_id, coll, fp_failed, ver_failed, "h1", "w1", 100, 1.0,
            lease_duration_seconds=-10
        )
        reap_success = reap_stalled_staging(self.conn, doc_id, coll, fp_failed)
        self.assertTrue(reap_success)
        fail_success = fail_revoked_version(self.conn, doc_id, coll, fp_failed, "Worker lease timeout")
        self.assertTrue(fail_success)

        # Initial purge runs
        self.mock_chroma.delete(where={"version_id": ver_failed})
        self.assertEqual(self.mock_chroma.count(where={"version_id": ver_failed}), 0)

        # 2. Delayed write arrives in ChromaDB for V1 AFTER initial purge
        late_meta = {
            "document_id": doc_id,
            "collection_name": coll,
            "index_fingerprint": fp_failed,
            "version_id": ver_failed
        }
        self.mock_chroma.add(
            ids=["late_chunk_1", "late_chunk_2"],
            embeddings=[[0.1]*384, [0.2]*384],
            documents=["Delayed regulation line 1", "Delayed regulation line 2"],
            metadatas=[late_meta, late_meta]
        )
        self.assertEqual(self.mock_chroma.count(where={"version_id": ver_failed}), 2)

        # 3. Retrieval exclusion verification: despite vectors existing in ChromaDB,
        # retrieve_active_corpus returns empty because V1 is not in document_registry
        res = retrieve_active_corpus(self.conn, self.mock_chroma, coll, [[0.1]*384], top_k=5)
        self.assertEqual(len(res["ids"][0]), 0)

        # 4. Scheduled reconciliation sweeper executes
        purged_count = run_reconciliation_sweeper(self.conn, self.mock_chroma, coll)
        self.assertEqual(purged_count, 1)

        # 5. Verify late vectors were purged from ChromaDB
        self.assertEqual(self.mock_chroma.count(where={"version_id": ver_failed}), 0)

        # 6. Verify idempotency: running sweeper a second time does not fail and deletes 0
        second_purge = run_reconciliation_sweeper(self.conn, self.mock_chroma, coll)
        self.assertEqual(second_purge, 1) # Scans same dead version, calls delete (idempotent no-op in ChromaDB)
        self.assertEqual(self.mock_chroma.count(where={"version_id": ver_failed}), 0)

        # 7. Final retrieval check remains isolated and clean
        res_after = retrieve_active_corpus(self.conn, self.mock_chroma, coll, [[0.1]*384], top_k=5)
        self.assertEqual(len(res_after["ids"][0]), 0)

    def test_reconciliation_collection_scoping_regression(self) -> None:
        """
        Regression test for collection scoping in run_reconciliation_sweeper().
        Tests:
        1. A failed version in collection A is purged when sweeping collection A.
        2. A revoked version in collection B is NOT selected when sweeping collection A.
        3. A failed version in collection B remains untouched when sweeping collection A.
        4. An expired superseded version in collection B remains untouched when sweeping collection A.
        5. Sweeping without a collection filter processes eligible versions across both collections.
        6. Repeated sweeps remain idempotent.
        """
        # 1. Setup SQLite records across two collections: col_A and col_B
        # Collection A: failed version
        self.conn.execute(
            """
            INSERT INTO version_lifecycle VALUES 
            ('DOC_A', 'col_A', 'fp_fail_A', 'v_fail_A', 'failed', 'h', 'w', 1, 1.0, 1, NULL,
             '2026-01-01', datetime('now'), '2026-01-01', 2, 200, NULL, NULL);
            """
        )
        
        # Collection B: revoked version
        self.conn.execute(
            """
            INSERT INTO version_lifecycle VALUES 
            ('DOC_B1', 'col_B', 'fp_rev_B', 'v_rev_B', 'revoked', 'h', 'w', 1, 1.0, 1, NULL,
             '2026-01-01', datetime('now'), '2026-01-01', 2, 200, NULL, NULL);
            """
        )
        
        # Collection B: failed version
        self.conn.execute(
            """
            INSERT INTO version_lifecycle VALUES 
            ('DOC_B2', 'col_B', 'fp_fail_B', 'v_fail_B', 'failed', 'h', 'w', 1, 1.0, 1, NULL,
             '2026-01-01', datetime('now'), '2026-01-01', 2, 200, NULL, NULL);
            """
        )
        
        # Collection B: expired superseded version (> 30 days old)
        self.conn.execute(
            """
            INSERT INTO version_lifecycle VALUES 
            ('DOC_B3', 'col_B', 'fp_sup_exp_B', 'v_sup_exp_B', 'superseded', 'h', 'w', 1, 1.0, 1, NULL,
             '2025-12-01', datetime('now', '-40 days'), '2025-12-01', 2, 200, NULL, NULL);
            """
        )

        # Collection B: active version (must never be purged)
        self.conn.execute(
            """
            INSERT INTO version_lifecycle VALUES 
            ('DOC_B4', 'col_B', 'fp_act_B', 'v_act_B', 'active', 'h', 'w', 1, 1.0, 1, NULL,
             '2026-01-01', datetime('now'), '2026-01-01', 2, 200, NULL, NULL);
            """
        )
        self.conn.execute(
            """
            INSERT INTO document_registry VALUES 
            ('DOC_B4', 'col_B', 'fp_act_B', 'v_act_B', 2, 200, '2026-01-01', 'w');
            """
        )

        # Collection B: recent superseded version (< 30 days old, must never be purged)
        self.conn.execute(
            """
            INSERT INTO version_lifecycle VALUES 
            ('DOC_B5', 'col_B', 'fp_sup_rec_B', 'v_sup_rec_B', 'superseded', 'h', 'w', 1, 1.0, 1, NULL,
             '2026-01-01', datetime('now', '-5 days'), '2026-01-01', 2, 200, NULL, NULL);
            """
        )

        # 2. Populate MockChromaCollection with chunks for each version (2 chunks per version = 12 total)
        def make_chunks(doc_id, coll, fp, ver_id):
            return [
                {"document_id": doc_id, "collection_name": coll, "index_fingerprint": fp, "version_id": ver_id},
                {"document_id": doc_id, "collection_name": coll, "index_fingerprint": fp, "version_id": ver_id}
            ]

        self.mock_chroma.add(
            ids=["fail_A_1", "fail_A_2"],
            embeddings=[[0.1]*384, [0.1]*384],
            documents=["Doc A fail 1", "Doc A fail 2"],
            metadatas=make_chunks("DOC_A", "col_A", "fp_fail_A", "v_fail_A")
        )
        self.mock_chroma.add(
            ids=["rev_B_1", "rev_B_2"],
            embeddings=[[0.1]*384, [0.1]*384],
            documents=["Doc B rev 1", "Doc B rev 2"],
            metadatas=make_chunks("DOC_B1", "col_B", "fp_rev_B", "v_rev_B")
        )
        self.mock_chroma.add(
            ids=["fail_B_1", "fail_B_2"],
            embeddings=[[0.1]*384, [0.1]*384],
            documents=["Doc B fail 1", "Doc B fail 2"],
            metadatas=make_chunks("DOC_B2", "col_B", "fp_fail_B", "v_fail_B")
        )
        self.mock_chroma.add(
            ids=["sup_exp_B_1", "sup_exp_B_2"],
            embeddings=[[0.1]*384, [0.1]*384],
            documents=["Doc B sup exp 1", "Doc B sup exp 2"],
            metadatas=make_chunks("DOC_B3", "col_B", "fp_sup_exp_B", "v_sup_exp_B")
        )
        self.mock_chroma.add(
            ids=["act_B_1", "act_B_2"],
            embeddings=[[0.1]*384, [0.1]*384],
            documents=["Doc B act 1", "Doc B act 2"],
            metadatas=make_chunks("DOC_B4", "col_B", "fp_act_B", "v_act_B")
        )
        self.mock_chroma.add(
            ids=["sup_rec_B_1", "sup_rec_B_2"],
            embeddings=[[0.1]*384, [0.1]*384],
            documents=["Doc B sup rec 1", "Doc B sup rec 2"],
            metadatas=make_chunks("DOC_B5", "col_B", "fp_sup_rec_B", "v_sup_rec_B")
        )
        self.assertEqual(self.mock_chroma.count(), 12)

        # 3. Sweep ONLY collection 'col_A'
        purged_A = run_reconciliation_sweeper(self.conn, self.mock_chroma, collection_name="col_A")
        
        # Verify requirement 1: A failed version in col_A is purged
        self.assertEqual(purged_A, 1)
        self.assertEqual(self.mock_chroma.count(where={"version_id": "v_fail_A"}), 0)

        # Verify requirement 2: A revoked version in col_B is NOT selected when sweeping col_A
        self.assertEqual(self.mock_chroma.count(where={"version_id": "v_rev_B"}), 2)

        # Verify requirement 3: A failed version in col_B remains untouched when sweeping col_A
        self.assertEqual(self.mock_chroma.count(where={"version_id": "v_fail_B"}), 2)

        # Verify requirement 4: An expired superseded version in col_B remains untouched when sweeping col_A
        self.assertEqual(self.mock_chroma.count(where={"version_id": "v_sup_exp_B"}), 2)

        # Active and recent superseded in col_B also remain untouched
        self.assertEqual(self.mock_chroma.count(where={"version_id": "v_act_B"}), 2)
        self.assertEqual(self.mock_chroma.count(where={"version_id": "v_sup_rec_B"}), 2)
        self.assertEqual(self.mock_chroma.count(), 10)

        # Verify requirement 6 (part 1): Repeated sweeps on col_A are idempotent
        repeat_A = run_reconciliation_sweeper(self.conn, self.mock_chroma, collection_name="col_A")
        self.assertEqual(repeat_A, 1) # Same version scanned, delete called, 0 in DB
        self.assertEqual(self.mock_chroma.count(where={"version_id": "v_fail_A"}), 0)
        self.assertEqual(self.mock_chroma.count(), 10)

        # 4. Verify requirement 5: Sweep without collection filter (collection_name=None)
        # Should process eligible versions across both collections:
        # Eligible: v_fail_A (already purged in ChromaDB), v_rev_B, v_fail_B, v_sup_exp_B
        # Total distinct eligible version_ids = 4
        global_purged = run_reconciliation_sweeper(self.conn, self.mock_chroma, collection_name=None)
        self.assertEqual(global_purged, 4)

        # Vectors for dead versions in col_B are now purged
        self.assertEqual(self.mock_chroma.count(where={"version_id": "v_rev_B"}), 0)
        self.assertEqual(self.mock_chroma.count(where={"version_id": "v_fail_B"}), 0)
        self.assertEqual(self.mock_chroma.count(where={"version_id": "v_sup_exp_B"}), 0)

        # Active and recent superseded versions MUST remain intact
        self.assertEqual(self.mock_chroma.count(where={"version_id": "v_act_B"}), 2)
        self.assertEqual(self.mock_chroma.count(where={"version_id": "v_sup_rec_B"}), 2)
        self.assertEqual(self.mock_chroma.count(), 4)

        # Verify requirement 6 (part 2): Repeated global sweep remains idempotent
        repeat_global = run_reconciliation_sweeper(self.conn, self.mock_chroma, collection_name=None)
        self.assertEqual(repeat_global, 4)
        self.assertEqual(self.mock_chroma.count(), 4)


if __name__ == "__main__":
    unittest.main()
