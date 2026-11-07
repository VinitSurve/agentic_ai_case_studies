#!/usr/bin/env python3
"""
PolicyLens (Case Study 2) – Thin Ingestion CLI Wrapper

Assignment-compatible CLI wrapper delegating directly to core indexing pipeline functions.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from CS2_PolicyLens.src.config import config
from CS2_PolicyLens.src.indexing_pipeline import index_pdf_document
from CS2_PolicyLens.src.version_registry import get_database_connection


def main() -> None:
    parser = argparse.ArgumentParser(description="PolicyLens Document Ingestion CLI")
    parser.add_argument("--pdf", type=str, help="Path to regulatory PDF file to index")
    parser.add_argument("--doc-id", type=str, default=None, help="Document ID (defaults to PDF stem)")
    parser.add_argument(
        "--collection",
        type=str,
        default="policylens_structure",
        choices=["policylens_structure", "policylens_fixed"],
        help="Target vector collection",
    )
    parser.add_argument("--status", action="store_true", help="Display active document registry status")

    args = parser.parse_args()

    if args.status:
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
        return

    if not args.pdf:
        print("Error: --pdf path is required (or use --status).")
        parser.print_help()
        sys.exit(1)

    print(f"[*] Ingesting PDF: {args.pdf}")
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
        print(f"[-] Ingestion Failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

