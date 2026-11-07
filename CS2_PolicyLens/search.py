#!/usr/bin/env python3
"""
PolicyLens (Case Study 2) – Unified Search & Question Answering CLI

Supports both assignment and legacy CLI signatures:
1. Positional query with top_k and filter:
   python search.py "cash disbursement limit for secured loans" --top_k 5 --filter issuer=RBI
2. Flag-based search:
   python search.py --query "margin requirements" --collection policylens_v1
3. Grounded regulatory question-answering:
   python search.py --ask "What is the penalty for late pension disbursement?"
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from CS2_PolicyLens.src.config import config
from CS2_PolicyLens.src.indexing_pipeline import query_policy_corpus
from CS2_PolicyLens.src.rag_qa import RegulatoryQAEngine
from CS2_PolicyLens.src.version_registry import get_database_connection


def _load_manifest_metadata() -> dict[str, dict[str, str]]:
    """Loads doc_id -> {title, issuer, url, date} from manifest.csv."""
    manifest_file = config.MANIFEST_FILE
    mapping: dict[str, dict[str, str]] = {}
    if manifest_file.is_file():
        try:
            with open(manifest_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    mapping[r["doc_id"]] = {
                        "title": r.get("title", ""),
                        "issuer": r.get("issuer", ""),
                        "issue_date": r.get("issue_date", ""),
                        "url": r.get("url", ""),
                    }
        except Exception:
            pass
    return mapping


def _determine_default_collection() -> str:
    """Selects policylens_v1 if populated, else policylens_structure."""
    db_file = config.REGISTRY_DB_PATH
    if db_file.is_file():
        try:
            conn = get_database_connection(db_file)
            row = conn.execute(
                "SELECT COUNT(*) FROM document_registry WHERE collection_name = 'policylens_v1'"
            ).fetchone()
            conn.close()
            if row and row[0] > 0:
                return "policylens_v1"
        except Exception:
            pass
    return "policylens_structure"


def main() -> None:
    parser = argparse.ArgumentParser(description="PolicyLens Search & Regulatory QA CLI")
    parser.add_argument(
        "positional_query",
        nargs="?",
        default=None,
        help="Search query text (positional syntax)",
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="Search query text (flag syntax)",
    )
    parser.add_argument(
        "--ask",
        type=str,
        default=None,
        help="Ask a regulatory question grounded strictly in active documents",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default=None,
        help="Target vector collection (defaults to policylens_v1 or policylens_structure)",
    )
    parser.add_argument(
        "--top_k",
        "--top-k",
        type=int,
        default=5,
        dest="top_k",
        help="Number of retrieved results (default: 5)",
    )
    parser.add_argument(
        "--filter",
        type=str,
        default=None,
        help="Optional metadata filter, e.g. --filter issuer=RBI",
    )

    args = parser.parse_args()

    # Determine query string
    active_query = args.positional_query or args.query
    if not active_query and not args.ask:
        parser.print_help()
        sys.exit(1)

    target_collection = args.collection or _determine_default_collection()
    manifest_meta = _load_manifest_metadata()

    # Parse optional filter
    filter_key, filter_val = None, None
    allowed_doc_ids: set[str] | None = None
    if args.filter:
        if "=" in args.filter:
            filter_key, filter_val = args.filter.split("=", 1)
            filter_key = filter_key.strip().lower()
            filter_val = filter_val.strip().lower()
            if filter_key == "issuer":
                allowed_doc_ids = {
                    did
                    for did, meta in manifest_meta.items()
                    if filter_val in meta.get("issuer", "").lower()
                }
                # Also include document IDs prefixed with issuer shorthand (rbi_, sebi_, dfs_, irdai_)
                prefix = f"{filter_val}_"
                for did in manifest_meta:
                    if did.lower().startswith(prefix):
                        allowed_doc_ids.add(did)
                print(f"[*] Applied metadata filter '{args.filter}' ({len(allowed_doc_ids)} matching documents).")

    # Mode 1: Search Query
    if active_query:
        print(f"[*] Searching collection '{target_collection}': \"{active_query}\"")
        raw_hits = query_policy_corpus(
            query=active_query,
            collection_name=target_collection,
            top_k=args.top_k * 4 if allowed_doc_ids else args.top_k,
        )

        hits: list[dict[str, Any]] = []
        for h in raw_hits:
            did = h.get("document_id", "")
            # Enrich with manifest metadata if missing
            if did in manifest_meta:
                if not h.get("title"):
                    h["title"] = manifest_meta[did].get("title", did)
                if not h.get("issuer"):
                    h["issuer"] = manifest_meta[did].get("issuer", "")

            # Filter check
            if allowed_doc_ids is not None:
                prefix = f"{filter_val}_"
                issuer_match = filter_val in (h.get("issuer") or "").lower()
                prefix_match = did.lower().startswith(prefix)
                id_match = did in allowed_doc_ids
                if not (issuer_match or prefix_match or id_match):
                    continue

            hits.append(h)
            if len(hits) >= args.top_k:
                break

        if not hits:
            print("[-] No active indexed content found matching query and filter.")
            return

        print(f"[+] Found {len(hits)} matching chunks (Active Versions Only):")
        for idx, hit in enumerate(hits, 1):
            score_str = f" | Cosine Score: {hit['score']:.4f}" if hit.get("score") is not None else ""
            title_str = hit.get("title") or hit.get("document_id")
            issuer_str = f" ({hit.get('issuer')})" if hit.get("issuer") else ""
            section_str = hit.get("section_heading") or "General"
            page_str = hit.get("page_number", 1)

            print(f"\n--- Result {idx} | {title_str}{issuer_str} ---")
            print(f"    Document ID: {hit['document_id']} | Page: {page_str} | Section: {section_str}{score_str}")
            print(f"    Text Preview:")
            body = hit.get("text", "").strip()
            # Clean preview
            lines = [l for l in body.split("\n") if l.strip() and not l.startswith("[")]
            preview = " ".join(lines[:4])
            if len(preview) > 300:
                preview = preview[:297] + "..."
            print(f"    {preview}")

    # Mode 2: Grounded QA
    elif args.ask:
        print(f"[*] Processing Grounded Question: \"{args.ask}\"")
        qa_engine = RegulatoryQAEngine(
            collection_name=target_collection,
            top_k=args.top_k,
        )
        res = qa_engine.answer_question(
            query=args.ask,
            collection_name=target_collection,
            top_k=args.top_k,
        )

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


if __name__ == "__main__":
    main()
