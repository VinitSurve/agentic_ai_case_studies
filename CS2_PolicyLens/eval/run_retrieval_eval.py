"""
PolicyLens (Case Study 2) – Retrieval Evaluation Runner

Evaluates and compares:
1. Structure-Aware Chunking (policylens_structure)
2. Fixed-Size Sliding Window Chunking (policylens_fixed)

Calculates:
- Recall@3
- Recall@5
- Recall@10
- Mean Reciprocal Rank (MRR)
"""

from __future__ import annotations

import csv
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Add repository root to sys.path
repo_root = Path(__file__).resolve().parent.parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from CS2_PolicyLens.src.config import config
from CS2_PolicyLens.src.indexing_pipeline import query_policy_corpus

logging.basicConfig(level=logging.WARNING)

EVAL_DIR = Path(__file__).resolve().parent
QUESTIONS_FILE = EVAL_DIR / "questions.csv"
RESULTS_FILE = EVAL_DIR / "retrieval_results.csv"
METRICS_FILE = EVAL_DIR / "metrics.json"


def is_hit(chunk: dict[str, Any], gold_doc_id: str, gold_page: int, gold_text: str) -> bool:
    """
    A hit means the retrieved chunk matches the gold document and overlaps the gold page
    or contains substantial substantive gold text keywords.
    """
    doc_id = chunk.get("document_id") or ""
    if doc_id != gold_doc_id:
        return False

    chunk_page = chunk.get("page_number")
    # Exact page match or immediate boundary overlap (+-1)
    if chunk_page is not None and abs(chunk_page - gold_page) <= 1:
        return True

    # Secondary text check if page metadata drifted
    txt = (chunk.get("text") or "").lower()
    gold_words = [w.lower() for w in gold_text.split() if len(w) > 4]
    overlap_count = sum(1 for w in gold_words if w in txt)
    if len(gold_words) > 0 and (overlap_count / len(gold_words)) >= 0.4:
        return True

    return False


def evaluate_retrieval() -> None:
    if not QUESTIONS_FILE.is_file():
        raise FileNotFoundError(f"Missing evaluation questions file: {QUESTIONS_FILE}")

    with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        questions = list(reader)

    print(f"Loaded {len(questions)} evaluation questions from {QUESTIONS_FILE.name}")

    # Pre-load shared embedding engine and DB connection for speed
    from CS2_PolicyLens.src.embeddings import EmbeddingEngine
    from CS2_PolicyLens.src.version_registry import get_database_connection
    from CS2_PolicyLens.src.indexing_pipeline import get_chroma_collection

    engine = EmbeddingEngine()
    db_conn = get_database_connection(config.REGISTRY_DB_PATH)

    results_rows: list[dict[str, Any]] = []

    metrics = {
        "structure_aware": {"r_at_3": 0, "r_at_5": 0, "r_at_10": 0, "mrr_sum": 0.0, "count": len(questions)},
        "fixed_window": {"r_at_3": 0, "r_at_5": 0, "r_at_10": 0, "mrr_sum": 0.0, "count": len(questions)},
    }

    disagreements: list[dict[str, Any]] = []

    for q in questions:
        qid = q["question_id"]
        query = q["question"]
        gold_doc = q["gold_document_id"]
        gold_page = int(q["gold_page_number"])
        gold_text = q.get("gold_evidence_text", "")
        q_type = q.get("question_type", "standard")

        # 1. Query Structure-Aware Collection
        hits_struct = query_policy_corpus(
            query=query,
            collection_name="policylens_structure",
            top_k=10,
            embedding_engine=engine,
        )
        rank_struct = None
        for idx, h in enumerate(hits_struct, 1):
            if is_hit(h, gold_doc, gold_page, gold_text):
                rank_struct = idx
                break

        # 2. Query Fixed-Window Collection
        hits_fixed = query_policy_corpus(
            query=query,
            collection_name="policylens_fixed",
            top_k=10,
            embedding_engine=engine,
        )
        rank_fixed = None
        for idx, h in enumerate(hits_fixed, 1):
            if is_hit(h, gold_doc, gold_page, gold_text):
                rank_fixed = idx
                break

        # Record metrics for structure-aware
        if rank_struct is not None:
            metrics["structure_aware"]["mrr_sum"] += 1.0 / rank_struct
            if rank_struct <= 3:
                metrics["structure_aware"]["r_at_3"] += 1
            if rank_struct <= 5:
                metrics["structure_aware"]["r_at_5"] += 1
            if rank_struct <= 10:
                metrics["structure_aware"]["r_at_10"] += 1

        # Record metrics for fixed-window
        if rank_fixed is not None:
            metrics["fixed_window"]["mrr_sum"] += 1.0 / rank_fixed
            if rank_fixed <= 3:
                metrics["fixed_window"]["r_at_3"] += 1
            if rank_fixed <= 5:
                metrics["fixed_window"]["r_at_5"] += 1
            if rank_fixed <= 10:
                metrics["fixed_window"]["r_at_10"] += 1

        results_rows.append({
            "question_id": qid,
            "question": query,
            "question_type": q_type,
            "gold_doc": gold_doc,
            "gold_page": gold_page,
            "struct_rank": rank_struct if rank_struct else -1,
            "struct_top1_doc": hits_struct[0]["document_id"] if hits_struct else "None",
            "struct_top1_page": hits_struct[0]["page_number"] if hits_struct else "None",
            "struct_top1_score": hits_struct[0]["score"] if hits_struct else 0.0,
            "fixed_rank": rank_fixed if rank_fixed else -1,
            "fixed_top1_doc": hits_fixed[0]["document_id"] if hits_fixed else "None",
            "fixed_top1_page": hits_fixed[0]["page_number"] if hits_fixed else "None",
            "fixed_top1_score": hits_fixed[0]["score"] if hits_fixed else 0.0,
        })

        # Track meaningful disagreements in top-3 retrieval
        hit_struct_top3 = (rank_struct is not None and rank_struct <= 3)
        hit_fixed_top3 = (rank_fixed is not None and rank_fixed <= 3)
        if hit_struct_top3 != hit_fixed_top3:
            disagreements.append({
                "question_id": qid,
                "question": query,
                "question_type": q_type,
                "struct_rank": rank_struct,
                "fixed_rank": rank_fixed,
                "advantage": "structure_aware" if hit_struct_top3 else "fixed_window",
            })

    # Summary aggregations
    N = len(questions)
    summary = {
        "total_questions": N,
        "structure_aware": {
            "recall_at_3": round(metrics["structure_aware"]["r_at_3"] / N, 4),
            "recall_at_5": round(metrics["structure_aware"]["r_at_5"] / N, 4),
            "recall_at_10": round(metrics["structure_aware"]["r_at_10"] / N, 4),
            "mrr": round(metrics["structure_aware"]["mrr_sum"] / N, 4),
            "raw_hits": {
                "top3": metrics["structure_aware"]["r_at_3"],
                "top5": metrics["structure_aware"]["r_at_5"],
                "top10": metrics["structure_aware"]["r_at_10"],
            }
        },
        "fixed_window": {
            "recall_at_3": round(metrics["fixed_window"]["r_at_3"] / N, 4),
            "recall_at_5": round(metrics["fixed_window"]["r_at_5"] / N, 4),
            "recall_at_10": round(metrics["fixed_window"]["r_at_10"] / N, 4),
            "mrr": round(metrics["fixed_window"]["mrr_sum"] / N, 4),
            "raw_hits": {
                "top3": metrics["fixed_window"]["r_at_3"],
                "top5": metrics["fixed_window"]["r_at_5"],
                "top10": metrics["fixed_window"]["r_at_10"],
            }
        },
        "disagreements": disagreements,
    }

    # Write results CSV
    with open(RESULTS_FILE, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "question_id", "question", "question_type", "gold_doc", "gold_page",
            "struct_rank", "struct_top1_doc", "struct_top1_page", "struct_top1_score",
            "fixed_rank", "fixed_top1_doc", "fixed_top1_page", "fixed_top1_score",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results_rows)

    # Write metrics JSON
    with open(METRICS_FILE, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n========================================================")
    print("RETRIEVAL EVALUATION RESULTS SUMMARY (25 Questions)")
    print("========================================================")
    print(f"Structure-Aware Chunking:")
    print(f"  Recall@3:  {summary['structure_aware']['recall_at_3'] * 100:.1f}% ({summary['structure_aware']['raw_hits']['top3']}/{N})")
    print(f"  Recall@5:  {summary['structure_aware']['recall_at_5'] * 100:.1f}% ({summary['structure_aware']['raw_hits']['top5']}/{N})")
    print(f"  Recall@10: {summary['structure_aware']['recall_at_10'] * 100:.1f}% ({summary['structure_aware']['raw_hits']['top10']}/{N})")
    print(f"  MRR:       {summary['structure_aware']['mrr']:.4f}")
    print("--------------------------------------------------------")
    print(f"Fixed-Window Baseline (500 tokens, 50 overlap):")
    print(f"  Recall@3:  {summary['fixed_window']['recall_at_3'] * 100:.1f}% ({summary['fixed_window']['raw_hits']['top3']}/{N})")
    print(f"  Recall@5:  {summary['fixed_window']['recall_at_5'] * 100:.1f}% ({summary['fixed_window']['raw_hits']['top5']}/{N})")
    print(f"  Recall@10: {summary['fixed_window']['recall_at_10'] * 100:.1f}% ({summary['fixed_window']['raw_hits']['top10']}/{N})")
    print(f"  MRR:       {summary['fixed_window']['mrr']:.4f}")
    print("========================================================")
    print(f"Disagreements in Top-3 ({len(disagreements)} instances):")
    for d in disagreements[:5]:
        print(f"  [{d['question_id']}] ({d['question_type']}): Struct Rank={d['struct_rank']}, Fixed Rank={d['fixed_rank']} -> {d['advantage'].upper()} ADVANTAGE")


if __name__ == "__main__":
    evaluate_retrieval()
