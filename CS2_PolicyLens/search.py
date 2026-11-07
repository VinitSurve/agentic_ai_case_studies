#!/usr/bin/env python3
"""
PolicyLens (Case Study 2) – Thin Search & Question Answering CLI Wrapper

Assignment-compatible search CLI wrapper delegating directly to core retrieval and QA functions.
Supports metadata filtering: e.g. --filter issuer=RBI
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


def _load_issuer_map() -> dict[str, str]:
    """Loads doc_id -> issuer mapping from manifest.csv."""
    manifest_file = config.MANIFEST_FILE
    mapping = {}
    if manifest_file.is_file():
        try:
            with open(manifest_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    mapping[r["doc_id"]] = r.get("issuer", "")
        except Exception:
            pass
    return mapping


def main() -> None:
    parser = argparse.ArgumentParser(description="PolicyLens Search & Regulatory QA CLI")
    parser.add_argument("--query", type=str, help="Search query against active indexed corpus")
    parser.add_argument("--ask", type=str, help="Ask a regulatory question grounded strictly in active documents")
    parser.add_argument(
        "--collection",
        type=str,
        default="policylens_structure",
        choices=["policylens_structure", "policylens_fixed"],
        help="Target vector collection",
    )
    parser.add_argument("--top-k", type=int, default=5, help="Number of retrieved results")
    parser.add_argument(
        "--filter",
        type=str,
        default=None,
        help="Optional metadata filter, e.g. --filter issuer=RBI",
    )

    args = parser.parse_args()

    if not args.query and not args.ask:
        parser.print_help()
        sys.exit(1)

    # Parse optional filter
    filter_key, filter_val = None, None
    allowed_doc_ids: set[str] | None = None
    if args.filter:
        if "=" in args.filter:
            filter_key, filter_val = args.filter.split("=", 1)
            filter_key = filter_key.strip().lower()
            filter_val = filter_val.strip().lower()
            if filter_key == "issuer":
                issuer_map = _load_issuer_map()
                allowed_doc_ids = {
                    did for did, iss in issuer_map.items() if filter_val in iss.lower()
                }
                # Also include document IDs prefixed with issuer shorthand (e.g. rbi_, sebi_, irdai_, dfs_)
                prefix = f"{filter_val}_"
                print(f"[*] Applied issuer filter '{filter_val}'.")

    # Mode 1: Search Query
    if args.query:
        print(f"[*] Searching collection '{args.collection}': \"{args.query}\"")
        hits = query_policy_corpus(
            query=args.query,
            collection_name=args.collection,
            top_k=args.top_k * 2 if allowed_doc_ids else args.top_k,
        )

        if allowed_doc_ids is not None:
            prefix = f"{filter_val}_"
            hits = [
                h for h in hits
                if (h.get("document_id") in allowed_doc_ids or (h.get("document_id") or "").startswith(prefix))
            ][:args.top_k]

        if not hits:
            print("[-] No active indexed content found matching query and filter.")
            return

        print(f"[+] Found {len(hits)} matching chunks:")
        for idx, hit in enumerate(hits, 1):
            score_str = f"(score: {hit['score']})" if hit["score"] is not None else ""
            print(f"\n--- Result {idx} | {hit['document_id']} (Page {hit['page_number']}) {score_str} ---")
            print(hit["text"][:300] + ("..." if len(hit["text"]) > 300 else ""))

    # Mode 2: Grounded QA
    elif args.ask:
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


if __name__ == "__main__":
    main()
