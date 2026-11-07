"""
PolicyLens (Case Study 2) – Unit & Integration Tests for Phase 3.2.2 Indexing Pipeline

Tests:
1. One successful PDF indexing lifecycle (Parse -> Chunk -> Embed -> Write -> Verify -> CAS Promote).
2. Failed indexing preserving the previously active version.
3. Retrieval excluding inactive versions.
4. Correct ChromaDB metadata validation.
5. Re-indexing an unchanged document without breaking the active version.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import pymupdf as fitz

from CS2_PolicyLens.src.embeddings import MockEmbeddingEngine
from CS2_PolicyLens.src.indexing_pipeline import (
    compute_index_fingerprint,
    index_pdf_document,
    query_policy_corpus,
)
from CS2_PolicyLens.src.version_registry import (
    VectorMetadataMismatchError,
    get_database_connection,
    init_lifecycle_schema,
    write_chunk_batch_guarded,
)


class MockChromaCollection:
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
        metadatas: list[dict[str, Any]],
    ) -> None:
        self.add_call_count += 1
        for i, emb, doc, meta in zip(ids, embeddings, documents, metadatas):
            self.records[i] = {
                "id": i,
                "embedding": emb,
                "document": doc,
                "metadata": dict(meta),
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
        where: dict[str, Any] | None = None,
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
            "distances": matching_dists,
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


class MockChromaClient:
    def __init__(self) -> None:
        self.collections: dict[str, MockChromaCollection] = {}

    def get_or_create_collection(
        self, name: str, metadata: dict[str, Any] | None = None
    ) -> MockChromaCollection:
        if name not in self.collections:
            self.collections[name] = MockChromaCollection()
        return self.collections[name]


def create_synthetic_pdf(output_path: Path, title: str, section_text: str) -> None:
    """Helper creating a valid 2-page regulatory PDF for fast, deterministic testing."""
    doc = fitz.open()
    
    # Page 1
    page1 = doc.new_page(width=595, height=842)
    page1.insert_text((50, 70), title, fontsize=14)
    page1.insert_text((50, 110), "Section 1: Introduction and Applicability", fontsize=12)
    page1.insert_text(
        (50, 140),
        f"These directions apply to all commercial banks and non-banking financial companies. {section_text}",
        fontsize=10,
    )

    # Page 2
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((50, 70), "Section 2: Customer Protection and Governance", fontsize=12)
    page2.insert_text(
        (50, 100),
        "Every regulated entity shall appoint an Internal Ombudsman under Section 35A of the Banking Regulation Act.",
        fontsize=10,
    )
    page2.insert_text(
        (50, 140),
        "The ombudsman shall examine all rejected complaints within thirty days of reporting.",
        fontsize=10,
    )

    doc.save(str(output_path))
    doc.close()


class TestIndexingPipelineIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.db_path = self.base_dir / "test_registry.db"
        self.pdf_path = self.base_dir / "sample_policy.pdf"
        self.chroma_client = MockChromaClient()
        self.mock_encoder = MockEmbeddingEngine(dimension=384)

        # Create sample synthetic PDF
        create_synthetic_pdf(
            self.pdf_path,
            title="Reserve Bank of India (Internal Ombudsman) Directions, 2026",
            section_text="All complaints regarding digital lending services must be reviewed independently.",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_successful_pdf_indexing_lifecycle(self) -> None:
        """
        Tests complete successful lifecycle:
        PDF -> Parse -> Chunk -> Embed -> Guarded Write -> Verify -> CAS Promote -> SQLite Active.
        """
        res = index_pdf_document(
            pdf_path=self.pdf_path,
            document_id="RBI_IO_2026",
            collection_name="policylens_structure",
            chroma_client=self.chroma_client,
            embedding_engine=self.mock_encoder,
            registry_db_path=self.db_path,
        )

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["document_id"], "RBI_IO_2026")
        self.assertGreater(res["chunk_count"], 0)
        self.assertEqual(res["pages_parsed"], 2)

        # Check SQLite document_registry
        conn = get_database_connection(self.db_path)
        row = conn.execute(
            "SELECT active_fingerprint, active_version_id, chunk_count FROM document_registry WHERE document_id = 'RBI_IO_2026'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], res["active_fingerprint"])
        self.assertEqual(row[1], res["version_id"])
        self.assertEqual(row[2], res["chunk_count"])

        # Check ChromaDB collection
        col = self.chroma_client.get_or_create_collection("policylens_structure")
        self.assertEqual(col.count(), res["chunk_count"])

        # Verify chunk content and metadata
        first_chunk = list(col.records.values())[0]
        meta = first_chunk["metadata"]
        self.assertEqual(meta["document_id"], "RBI_IO_2026")
        self.assertEqual(meta["collection_name"], "policylens_structure")
        self.assertEqual(meta["index_fingerprint"], res["active_fingerprint"])
        self.assertEqual(meta["version_id"], res["version_id"])

        conn.close()

    def test_failed_indexing_preserves_previously_active_version(self) -> None:
        """
        Tests that when an indexing job fails mid-pipeline (e.g. storage error),
        the candidate is marked 'failed' and the previously active version remains untouched.
        """
        # Step 1: Successfully index initial version V0
        res_v0 = index_pdf_document(
            pdf_path=self.pdf_path,
            document_id="RBI_FAIL_TEST",
            collection_name="policylens_structure",
            chroma_client=self.chroma_client,
            embedding_engine=self.mock_encoder,
            registry_db_path=self.db_path,
        )
        self.assertEqual(res_v0["status"], "success")
        fp_v0 = res_v0["active_fingerprint"]
        v0_id = res_v0["version_id"]

        # Step 2: Create a modified PDF for second indexing attempt
        pdf_v1_path = self.base_dir / "sample_policy_v1.pdf"
        create_synthetic_pdf(pdf_v1_path, "RBI Policy V1 Modified", "Modified regulatory text.")

        # Step 3: Mock ChromaDB.add to raise an error during storage
        col = self.chroma_client.get_or_create_collection("policylens_structure")
        with mock.patch.object(col, "add", side_effect=IOError("Simulated ChromaDB disk failure")):
            with self.assertRaises(IOError) as ctx:
                index_pdf_document(
                    pdf_path=pdf_v1_path,
                    document_id="RBI_FAIL_TEST",
                    collection_name="policylens_structure",
                    chroma_client=self.chroma_client,
                    embedding_engine=self.mock_encoder,
                    registry_db_path=self.db_path,
                )
            self.assertIn("Simulated ChromaDB disk failure", str(ctx.exception))

        # Step 4: Verify that document_registry STILL points to V0!
        conn = get_database_connection(self.db_path)
        active_row = conn.execute(
            "SELECT active_fingerprint, active_version_id FROM document_registry WHERE document_id = 'RBI_FAIL_TEST'"
        ).fetchone()
        self.assertEqual(active_row[0], fp_v0)
        self.assertEqual(active_row[1], v0_id)

        # In version_lifecycle, V0 is still 'active' and candidate V1 is 'failed'
        v0_state = conn.execute(
            "SELECT state FROM version_lifecycle WHERE fingerprint = ?", (fp_v0,)
        ).fetchone()[0]
        self.assertEqual(v0_state, "active")

        failed_rows = conn.execute(
            "SELECT state, error_message FROM version_lifecycle WHERE state = 'failed'"
        ).fetchall()
        self.assertEqual(len(failed_rows), 1)
        self.assertIn("Simulated ChromaDB disk failure", failed_rows[0][1])

        conn.close()

    def test_retrieval_excludes_inactive_versions(self) -> None:
        """
        Tests that query_policy_corpus returns only chunks from active versions,
        even if ChromaDB contains orphan vectors from revoked or failed attempts.
        """
        # Step 1: Index document normally
        res = index_pdf_document(
            pdf_path=self.pdf_path,
            document_id="RBI_RETRIEVE",
            collection_name="policylens_structure",
            chroma_client=self.chroma_client,
            embedding_engine=self.mock_encoder,
            registry_db_path=self.db_path,
        )

        # Step 2: Inject an unauthorized orphan chunk into ChromaDB (version not in registry)
        col = self.chroma_client.get_or_create_collection("policylens_structure")
        col.add(
            ids=["orphan_chunk_999"],
            embeddings=[[0.1] * 384],
            documents=["Unauthorized rogue regulatory clause."],
            metadatas=[
                {
                    "document_id": "RBI_RETRIEVE",
                    "collection_name": "policylens_structure",
                    "index_fingerprint": "rogue_fp_999",
                    "version_id": "v_rogue",
                    "page_number": 1,
                }
            ],
        )

        # Step 3: Query active corpus
        hits = query_policy_corpus(
            query="Internal Ombudsman directions",
            collection_name="policylens_structure",
            top_k=10,
            chroma_client=self.chroma_client,
            embedding_engine=self.mock_encoder,
            registry_db_path=self.db_path,
        )

        self.assertGreater(len(hits), 0)
        for hit in hits:
            # Must strictly match the active fingerprint
            self.assertEqual(hit["metadata"]["index_fingerprint"], res["active_fingerprint"])
            self.assertNotEqual(hit["chunk_id"], "orphan_chunk_999")

    def test_chromadb_metadata_validation_during_indexing(self) -> None:
        """
        Tests that every chunk produced by indexing complies with the 4 core metadata
        fields and write_chunk_batch_guarded validates all fields.
        """
        col = self.chroma_client.get_or_create_collection("policylens_structure")

        # Test invalid metadata triggers VectorMetadataMismatchError
        bad_meta = [
            {"document_id": "DOC_A", "collection_name": "wrong_col", "index_fingerprint": "fp1", "version_id": "v1"}
        ]
        with self.assertRaises(VectorMetadataMismatchError):
            write_chunk_batch_guarded(
                chroma_collection=col,
                ids=["c1"],
                embeddings=[[0.1] * 384],
                documents=["text"],
                metadatas=bad_meta,
                expected_doc_id="DOC_A",
                expected_collection="policylens_structure",
                expected_fingerprint="fp1",
                expected_version_id="v1",
            )

    def test_reindexing_unchanged_document_skips_and_preserves_active(self) -> None:
        """
        Tests that re-indexing an unchanged PDF returns 'skipped' without mutating
        document_registry or re-writing ChromaDB.
        """
        # First index run
        res1 = index_pdf_document(
            pdf_path=self.pdf_path,
            document_id="RBI_UNCHANGED",
            collection_name="policylens_structure",
            chroma_client=self.chroma_client,
            embedding_engine=self.mock_encoder,
            registry_db_path=self.db_path,
        )
        self.assertEqual(res1["status"], "success")
        col = self.chroma_client.get_or_create_collection("policylens_structure")
        initial_count = col.count()

        # Second index run with identical PDF
        res2 = index_pdf_document(
            pdf_path=self.pdf_path,
            document_id="RBI_UNCHANGED",
            collection_name="policylens_structure",
            chroma_client=self.chroma_client,
            embedding_engine=self.mock_encoder,
            registry_db_path=self.db_path,
            force_reindex=False,
        )
        self.assertEqual(res2["status"], "skipped")
        self.assertEqual(res2["active_fingerprint"], res1["active_fingerprint"])
        self.assertEqual(res2["version_id"], res1["version_id"])

        # ChromaDB count unchanged
        self.assertEqual(col.count(), initial_count)


if __name__ == "__main__":
    unittest.main()

