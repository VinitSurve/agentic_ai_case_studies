"""
PolicyLens (Case Study 2) – Unified Indexing & Retrieval Pipeline

Connects Phase 3.1 PDF Parser, Regulatory Chunker, and Local Embeddings
to Phase 3.2.1 SQLite Lifecycle Registry and ChromaDB Vector Storage.

Features:
- Complete atomic lifecycle: Register Staging -> Chunk -> Embed -> Guarded Write -> Verify -> CAS Promote.
- Automatic skip / idempotency for unchanged active document fingerprints.
- Error fencing: Failed runs transition to 'failed' and leave previous active versions intact.
- Active-only isolated vector retrieval.
- Demonstrable CLI interface for indexing sample PDFs and querying regulatory policies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import socket
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from CS2_PolicyLens.src.chunker import DocumentChunk, RegulatoryChunker
from CS2_PolicyLens.src.config import config
from CS2_PolicyLens.src.embeddings import EmbeddingEngine
from CS2_PolicyLens.src.pdf_parser import PDFParser
from CS2_PolicyLens.src.version_registry import (
    FencingRevokedError,
    LifecycleRegistryError,
    PromotionError,
    StalePromotionError,
    VectorMetadataMismatchError,
    get_database_connection,
    init_lifecycle_schema,
    promote_verified_candidate,
    register_staging_candidate,
    retrieve_active_corpus,
    run_reconciliation_sweeper,
    verify_staging_candidate,
    write_chunk_batch_guarded,
)

logger = logging.getLogger("PolicyLens.IndexingPipeline")


def compute_index_fingerprint(
    document_id: str,
    collection_name: str,
    pdf_bytes: bytes,
    model_name: str = "all-MiniLM-L6-v2",
    target_tokens: int = 350,
) -> str:
    """
    Computes a canonical SHA-256 fingerprint for a document index configuration.
    """
    pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    canonical_payload = {
        "document_id": document_id,
        "collection_name": collection_name,
        "pdf_sha256": pdf_sha256,
        "model_name": model_name,
        "target_tokens": target_tokens,
    }
    payload_str = json.dumps(canonical_payload, sort_keys=True)
    return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()


def get_chroma_collection(
    collection_name: str,
    chroma_client: Any | None = None,
) -> Any:
    """
    Returns or creates the specified ChromaDB collection.
    """
    if chroma_client is None:
        import chromadb

        config.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        chroma_client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))

    return chroma_client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": config.SIMILARITY_METRIC},
    )


def index_pdf_document(
    pdf_path: str | Path,
    document_id: str | None = None,
    collection_name: str = "policylens_structure",
    chroma_client: Any | None = None,
    embedding_engine: Any | None = None,
    registry_db_path: str | Path | None = None,
    force_reindex: bool = False,
) -> dict[str, Any]:
    """
    Executes the complete end-to-end indexing pipeline for a PDF document.

    Lifecycle Steps:
    1. Read and hash PDF bytes.
    2. Compute index fingerprint.
    3. Check if document is already actively indexed (skip if unchanged).
    4. Register staging candidate in SQLite lifecycle registry.
    5. Parse PDF using Phase 3.1 PDFParser.
    6. Chunk document using RegulatoryChunker.
    7. Generate embeddings using EmbeddingEngine on CPU.
    8. Write vectors to ChromaDB with guarded metadata validation.
    9. Verify candidate in SQLite.
    10. Atomically promote verified candidate to active using CAS.
    """
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(f"PDF file not found: {path.resolve()}")

    doc_id = (document_id or path.stem).strip()
    pdf_bytes = path.read_bytes()
    fingerprint = compute_index_fingerprint(doc_id, collection_name, pdf_bytes)

    # 1. Connect to SQLite Registry
    db_file = registry_db_path or config.REGISTRY_DB_PATH
    Path(db_file).parent.mkdir(parents=True, exist_ok=True)
    conn = get_database_connection(db_file)
    init_lifecycle_schema(conn)

    # 2. Check Idempotency: Skip if already actively indexed with identical fingerprint
    if not force_reindex:
        active_row = conn.execute(
            """
            SELECT active_fingerprint, active_version_id, chunk_count, total_tokens
            FROM document_registry
            WHERE document_id = ? AND collection_name = ?
            """,
            (doc_id, collection_name),
        ).fetchone()

        if active_row and active_row[0] == fingerprint:
            conn.close()
            return {
                "status": "skipped",
                "message": "Document is already actively indexed with identical fingerprint.",
                "document_id": doc_id,
                "collection_name": collection_name,
                "active_fingerprint": fingerprint,
                "version_id": active_row[1],
                "chunk_count": active_row[2],
                "total_tokens": active_row[3],
            }

    # 3. Setup Worker Identity & Candidate Version
    host_id = socket.gethostname()
    pid = os.getpid()
    process_start_time = time.time()
    worker_id = f"{host_id}_{pid}_{uuid.uuid4().hex[:8]}"
    version_id = f"{doc_id}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"

    # 4. Register Staging Candidate
    register_staging_candidate(
        conn=conn,
        document_id=doc_id,
        collection_name=collection_name,
        fingerprint=fingerprint,
        version_id=version_id,
        host_id=host_id,
        worker_id=worker_id,
        pid=pid,
        process_start_time=process_start_time,
    )

    try:
        # 5. Parse PDF using Phase 3.1 PDFParser
        parser = PDFParser()
        parsed_doc = parser.parse_bytes(pdf_bytes, doc_id, filename=path.name)

        # 6. Chunk Document
        chunker = RegulatoryChunker()
        chunks: list[DocumentChunk] = chunker.chunk(
            parsed_doc=parsed_doc,
            collection_name=collection_name,
            index_fingerprint=fingerprint,
            version_id=version_id,
        )

        if not chunks:
            raise ValueError(f"Zero substantive chunks generated for document '{doc_id}'.")

        # 7. Generate Embeddings (CPU Compatible)
        encoder = embedding_engine or EmbeddingEngine()
        chunk_texts = [c.text for c in chunks]
        embeddings = encoder.encode(chunk_texts)

        # 8. Guarded Write to ChromaDB
        chroma_col = get_chroma_collection(collection_name, chroma_client)
        chunk_ids = [c.chunk_id for c in chunks]
        metadatas = [c.metadata for c in chunks]

        write_chunk_batch_guarded(
            chroma_collection=chroma_col,
            ids=chunk_ids,
            embeddings=embeddings,
            documents=chunk_texts,
            metadatas=metadatas,
            expected_doc_id=doc_id,
            expected_collection=collection_name,
            expected_fingerprint=fingerprint,
            expected_version_id=version_id,
        )

        # 9. Verify Staging Candidate
        total_tokens = sum(c.token_count for c in chunks)
        verify_staging_candidate(
            conn=conn,
            document_id=doc_id,
            collection_name=collection_name,
            fingerprint=fingerprint,
            worker_id=worker_id,
            fencing_token=1,
            chunk_count=len(chunks),
            total_tokens=total_tokens,
            validation_report_json=json.dumps({"blocks": len(parsed_doc.blocks), "chunks": len(chunks)}),
        )

        # 10. Atomic CAS Promotion to Active
        promotion_result = promote_verified_candidate(
            conn=conn,
            document_id=doc_id,
            collection_name=collection_name,
            candidate_fingerprint=fingerprint,
            worker_id=worker_id,
            fencing_token=1,
            chunk_count=len(chunks),
            total_tokens=total_tokens,
        )

        conn.close()
        return {
            "status": "success",
            "message": "Document successfully parsed, embedded, indexed, and promoted.",
            "document_id": doc_id,
            "collection_name": collection_name,
            "active_fingerprint": fingerprint,
            "version_id": version_id,
            "chunk_count": len(chunks),
            "total_tokens": total_tokens,
            "pages_parsed": parsed_doc.total_pages,
        }

    except Exception as e:
        # On failure, mark candidate failed to preserve recovery invariants
        try:
            conn.execute(
                """
                UPDATE version_lifecycle
                SET state = 'failed',
                    error_message = ?,
                    updated_at = datetime('now')
                WHERE document_id = ? AND collection_name = ? AND fingerprint = ? 
                  AND worker_id = ? AND state IN ('staging', 'verified')
                """,
                (str(e), doc_id, collection_name, fingerprint, worker_id),
            )
        except Exception:
            pass
        conn.close()
        raise


def query_policy_corpus(
    query: str,
    collection_name: str = "policylens_structure",
    top_k: int = 5,
    chroma_client: Any | None = None,
    embedding_engine: Any | None = None,
    registry_db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """
    Queries indexed policies strictly through active registry fingerprints.
    """
    db_file = registry_db_path or config.REGISTRY_DB_PATH
    if not Path(db_file).is_file():
        return []

    conn = get_database_connection(db_file)
    init_lifecycle_schema(conn)

    # 1. Encode query
    encoder = embedding_engine or EmbeddingEngine()
    query_embeddings = encoder.encode([query])

    # 2. Get Chroma Collection
    chroma_col = get_chroma_collection(collection_name, chroma_client)

    # 3. Retrieve active corpus
    raw_results = retrieve_active_corpus(
        db_conn=conn,
        chroma_collection=chroma_col,
        collection_name=collection_name,
        query_embeddings=query_embeddings,
        top_k=top_k,
    )
    conn.close()

    # 4. Format results
    hits: list[dict[str, Any]] = []
    if not raw_results or not raw_results.get("ids") or not raw_results["ids"][0]:
        return hits

    ids = raw_results["ids"][0]
    docs = raw_results["documents"][0]
    metas = raw_results["metadatas"][0]
    dists = raw_results.get("distances", [[None] * len(ids)])[0]

    for chunk_id, doc_text, meta, dist in zip(ids, docs, metas, dists):
        hits.append(
            {
                "chunk_id": chunk_id,
                "document_id": meta.get("document_id"),
                "text": doc_text,
                "score": round(1.0 - dist, 4) if dist is not None else None,
                "page_number": meta.get("page_number"),
                "section_heading": meta.get("section_heading"),
                "metadata": meta,
            }
        )
    return hits


# =============================================================================
# CLI Entry Point
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="PolicyLens Phase 3.2 Indexing & Retrieval CLI"
    )
    parser.add_argument(
        "--index", action="store_true", help="Index a specified PDF document"
    )
    parser.add_argument(
        "--pdf", type=str, help="Path to regulatory PDF file to index"
    )
    parser.add_argument(
        "--doc-id", type=str, default=None, help="Document ID (defaults to PDF stem)"
    )
    parser.add_argument(
        "--collection",
        type=str,
        default="policylens_structure",
        choices=["policylens_structure", "policylens_fixed"],
        help="Target vector collection",
    )
    parser.add_argument(
        "--query", type=str, help="Search query against active indexed corpus"
    )
    parser.add_argument(
        "--ask", type=str, help="Ask a regulatory question grounded strictly in active documents"
    )
    parser.add_argument(
        "--top-k", type=int, default=5, help="Number of retrieved results"
    )
    parser.add_argument(
        "--status", action="store_true", help="Display active document registry status"
    )

    args = parser.parse_args()

    if args.index:
        if not args.pdf:
            print("Error: --pdf path is required when using --index")
            sys.exit(1)
        print(f"[*] Indexing PDF: {args.pdf}")
        try:
            res = index_pdf_document(
                pdf_path=args.pdf,
                document_id=args.doc_id,
                collection_name=args.collection,
            )
            print(f"[+] Status: {res['status'].upper()}")
            print(f"    Document ID: {res['document_id']}")
            print(f"    Version ID:  {res.get('version_id')}")
            print(f"    Fingerprint: {res.get('active_fingerprint')}")
            print(f"    Chunks:      {res.get('chunk_count')}")
            print(f"    Message:     {res['message']}")
        except Exception as e:
            print(f"[-] Indexing Failed: {e}")
            sys.exit(1)

    elif args.query:
        print(f"[*] Querying collection '{args.collection}': \"{args.query}\"")
        hits = query_policy_corpus(
            query=args.query,
            collection_name=args.collection,
            top_k=args.top_k,
        )
        if not hits:
            print("[-] No active indexed content found matching query.")
            return
        print(f"[+] Found {len(hits)} matching chunks:")
        for idx, hit in enumerate(hits, 1):
            score_str = f"(score: {hit['score']})" if hit["score"] is not None else ""
            print(f"\n--- Result {idx} | {hit['document_id']} (Page {hit['page_number']}) {score_str} ---")
            print(hit["text"][:300] + ("..." if len(hit["text"]) > 300 else ""))

    elif args.ask:
        from CS2_PolicyLens.src.rag_qa import RegulatoryQAEngine

        print(f"[*] Processing Question: \"{args.ask}\"")
        qa_engine = RegulatoryQAEngine(
            collection_name=args.collection,
            top_k=args.top_k,
        )
        res = qa_engine.answer_question(query=args.ask, collection_name=args.collection, top_k=args.top_k)

        print("\n" + "=" * 70)
        print("QUESTION:")
        print(res["question"])
        print("-" * 70)
        print("ANSWER:")
        print(res["answer"])
        print("-" * 70)
        print(f"STATUS: {res['status'].upper()}")
        print(f"ENGINE: {res.get('llm_used')}")
        print("=" * 70)

        sources = res.get("sources", [])
        if sources:
            print(f"\nSOURCES CITED ({len(sources)}):")
            for src in sources:
                score_str = f" | Score: {src['retrieval_score']}" if src.get("retrieval_score") is not None else ""
                print(
                    f"  [{src['source_index']}] Document: {src['document_id']} "
                    f"| Page: {src['page_number']} "
                    f"| Section: {src['section_heading']}{score_str}"
                )
        else:
            print("\nSOURCES CITED: None (Insufficient evidence context)")

    elif args.status:
        db_file = config.REGISTRY_DB_PATH
        if not db_file.is_file():
            print("[-] Registry database does not exist yet. No documents indexed.")
            return
        conn = get_database_connection(db_file)
        rows = conn.execute(
            """
            SELECT document_id, collection_name, active_fingerprint, active_version_id, chunk_count, promoted_at 
            FROM document_registry
            ORDER BY promoted_at DESC
            """
        ).fetchall()
        conn.close()
        if not rows:
            print("[*] Document registry is empty.")
            return
        print(f"[+] Active Document Registry ({len(rows)} documents indexed):")
        for r in rows:
            print(f"  • {r[0]} [{r[1]}] -> Version: {r[3]} | Chunks: {r[4]} | Promoted: {r[5]}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()

