#!/usr/bin/env python3
"""
PolicyLens (Case Study 2) – High-Throughput Regulatory Ingestion CLI

Assignment-compatible CLI supporting:
1. Directory / Manifest Ingestion:
   python ingest.py --input data/pdfs --manifest data/manifest.csv --collection policylens_v1
2. Single-PDF Ingestion:
   python ingest.py --pdf data/pdfs/sebi_currency_deriv_limits_2026.pdf
3. Status Inspection:
   python ingest.py --status
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from pathlib import Path
from typing import Any

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from CS2_PolicyLens.src.config import config
from CS2_PolicyLens.src.embeddings import EmbeddingEngine
from CS2_PolicyLens.src.indexing_pipeline import (
    get_chroma_collection,
    index_pdf_document,
)
from CS2_PolicyLens.src.version_registry import get_database_connection


def _show_registry_status(collection_filter: str | None = None) -> None:
    db_file = config.REGISTRY_DB_PATH
    if not db_file.is_file():
        print("[-] Registry database does not exist yet. No documents indexed.")
        return

    conn = get_database_connection(db_file)
    query = """
        SELECT document_id, collection_name, active_fingerprint, active_version_id, chunk_count, promoted_at 
        FROM document_registry
    """
    params: list[Any] = []
    if collection_filter:
        query += " WHERE collection_name = ?"
        params.append(collection_filter)
    query += " ORDER BY promoted_at DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()

    if not rows:
        col_str = f" in collection '{collection_filter}'" if collection_filter else ""
        print(f"[*] Document registry is empty{col_str}.")
        return

    col_title = f" [{collection_filter}]" if collection_filter else ""
    print(f"[+] Active Document Registry ({len(rows)} documents indexed{col_title}):")
    total_chunks = sum(r[4] for r in rows)
    for r in rows:
        print(f"  • {r[0]} [{r[1]}] -> Version: {r[3]} | Chunks: {r[4]} | Promoted: {r[5]}")
    print(f"[+] Total Active Documents: {len(rows)} | Total Chunks: {total_chunks}")


def _ingest_batch(
    input_path: Path,
    manifest_path: Path | None,
    collection_name: str,
    force_reindex: bool = False,
) -> dict[str, Any]:
    """Ingests a directory of PDFs with manifest metadata and SHA-256 caching."""
    import chromadb

    config.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    chroma_client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    embedding_engine = EmbeddingEngine()

    # Read manifest if provided
    manifest_rows: list[dict[str, str]] = []
    if manifest_path and manifest_path.is_file():
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest_rows = list(csv.DictReader(f))

    # Build target document list
    docs_to_process: list[dict[str, Any]] = []
    if manifest_rows:
        for r in manifest_rows:
            filename = r.get("filename") or f"{r.get('doc_id')}.pdf"
            p = input_path / filename if input_path.is_dir() else input_path
            docs_to_process.append({
                "doc_id": r.get("doc_id") or p.stem,
                "pdf_path": p,
                "title": r.get("title", ""),
                "issuer": r.get("issuer", ""),
                "page_count": int(r.get("page_count", 0)),
            })
    else:
        if input_path.is_dir():
            for p in sorted(input_path.glob("*.pdf")):
                docs_to_process.append({
                    "doc_id": p.stem,
                    "pdf_path": p,
                    "title": p.stem.replace("_", " ").title(),
                    "issuer": "Regulatory Authority",
                    "page_count": 0,
                })
        else:
            docs_to_process.append({
                "doc_id": input_path.stem,
                "pdf_path": input_path,
                "title": input_path.stem.replace("_", " ").title(),
                "issuer": "Regulatory Authority",
                "page_count": 0,
            })

    total_manifest = len(docs_to_process)
    indexed_count = 0
    skipped_count = 0
    failed_count = 0
    total_pages_processed = 0
    total_chunks_indexed = 0
    new_chunks_added = 0

    print(f"[*] Starting Batch Ingestion: {total_manifest} documents -> Collection '{collection_name}'")
    start_time = time.time()

    for idx, doc in enumerate(docs_to_process, 1):
        p = Path(doc["pdf_path"])
        doc_id = doc["doc_id"]
        doc_title = doc.get("title", "")
        doc_issuer = doc.get("issuer", "")

        if not p.is_file():
            print(f"  [{idx:02d}/{total_manifest:02d}] [-] MISSING FILE: {p.name}")
            failed_count += 1
            continue

        try:
            res = index_pdf_document(
                pdf_path=p,
                document_id=doc_id,
                collection_name=collection_name,
                chroma_client=chroma_client,
                embedding_engine=embedding_engine,
                force_reindex=force_reindex,
                metadata={"title": doc_title, "issuer": doc_issuer},
            )

            status = res["status"]
            chunks = res.get("chunk_count", 0)
            pages = res.get("pages_parsed", doc.get("page_count", 0))

            if status == "skipped":
                skipped_count += 1
                total_chunks_indexed += chunks
                total_pages_processed += pages
                print(f"  [{idx:02d}/{total_manifest:02d}] [~] SKIPPED (Idempotent): {doc_id} ({chunks} chunks)")
            elif status == "success":
                indexed_count += 1
                new_chunks_added += chunks
                total_chunks_indexed += chunks
                total_pages_processed += pages
                print(f"  [{idx:02d}/{total_manifest:02d}] [+] INDEXED: {doc_id} ({pages} pages, {chunks} chunks)")
            else:
                failed_count += 1
                print(f"  [{idx:02d}/{total_manifest:02d}] [-] FAILED: {doc_id} - {res.get('message')}")

        except Exception as e:
            failed_count += 1
            print(f"  [{idx:02d}/{total_manifest:02d}] [-] EXCEPTION: {doc_id} - {e}")

    duration = time.time() - start_time

    # Query active document count in this collection
    conn = get_database_connection(config.REGISTRY_DB_PATH)
    active_row = conn.execute(
        "SELECT COUNT(*), SUM(chunk_count) FROM document_registry WHERE collection_name = ?",
        (collection_name,),
    ).fetchone()
    conn.close()

    active_doc_count = active_row[0] if active_row else 0
    active_chunks = active_row[1] if active_row and active_row[1] else 0

    print("\n" + "=" * 65)
    print("INGESTION BATCH SUMMARY")
    print("=" * 65)
    print(f"Collection Name:             {collection_name}")
    print(f"Manifest Document Count:     {total_manifest}")
    print(f"Successfully Indexed:        {indexed_count}")
    print(f"Skipped (Unchanged/Cached):  {skipped_count}")
    print(f"Failed Count:                {failed_count}")
    print(f"Total Pages Processed:       {total_pages_processed}")
    print(f"Total Chunks Active:         {active_chunks}")
    print(f"New Chunks Added:            {new_chunks_added}")
    print(f"Active Document Count:       {active_doc_count}")
    print(f"Execution Duration:          {duration:.2f} seconds")
    print("=" * 65)

    return {
        "manifest_document_count": total_manifest,
        "successfully_indexed_count": indexed_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "total_pages_processed": total_pages_processed,
        "total_chunks_indexed": active_chunks,
        "new_chunks_added": new_chunks_added,
        "active_document_count": active_doc_count,
        "duration_seconds": round(duration, 3),
        "collection_name": collection_name,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="PolicyLens Document Ingestion CLI")
    parser.add_argument("--input", type=str, default=None, help="Path to PDF directory or file to index")
    parser.add_argument("--manifest", type=str, default=None, help="Path to manifest.csv metadata file")
    parser.add_argument("--pdf", type=str, default=None, help="Path to single regulatory PDF file")
    parser.add_argument("--doc-id", "--doc_id", type=str, default=None, help="Document ID (defaults to PDF stem)")
    parser.add_argument(
        "--collection",
        type=str,
        default="policylens_v1",
        help="Target vector collection (default: policylens_v1)",
    )
    parser.add_argument("--status", action="store_true", help="Display active document registry status")
    parser.add_argument("--force-reindex", action="store_true", help="Force reindexing even if fingerprint matches")

    args = parser.parse_args()

    if args.status:
        _show_registry_status(collection_filter=args.collection if args.collection != "policylens_v1" else None)
        return

    # Target path can come from --input or legacy --pdf
    target_input = args.input or args.pdf

    if not target_input:
        print("Error: --input or --pdf is required (or use --status).")
        parser.print_help()
        sys.exit(1)

    input_path = Path(target_input)
    manifest_path = Path(args.manifest) if args.manifest else None

    if input_path.is_dir() or manifest_path:
        # Batch directory ingestion
        _ingest_batch(
            input_path=input_path,
            manifest_path=manifest_path,
            collection_name=args.collection,
            force_reindex=args.force_reindex,
        )
    else:
        # Single file ingestion
        print(f"[*] Ingesting Single PDF: {input_path}")
        try:
            res = index_pdf_document(
                pdf_path=input_path,
                document_id=args.doc_id,
                collection_name=args.collection,
                force_reindex=args.force_reindex,
            )
            print(f"[+] Status: {res['status'].upper()}")
            print(f"    Document ID: {res['document_id']}")
            print(f"    Version ID:  {res.get('version_id')}")
            print(f"    Fingerprint: {res.get('active_fingerprint')}")
            print(f"    Chunks:      {res.get('chunk_count')}")
            print(f"    Message:     {res['message']}")
        except Exception as e:
            print(f"[-] Ingestion Failed: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
