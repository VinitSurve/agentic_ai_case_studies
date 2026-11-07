"""
PolicyLens (Case Study 2) – Retrieval Enhancement Evaluation Runner

Executes the complete 25-question evaluation benchmark against 3 configurations:
1. Baseline Dense Retrieval
2. Dense Retrieval + Lexical Boost
3. Dense Retrieval + Lexical Boost + Masthead Denoising

Also evaluates the 3 official NPA investigation queries and produces
comprehensive metrics (Recall@3, Recall@5, Recall@10, MRR).
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

repo_root = Path(__file__).resolve().parent.parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from CS2_PolicyLens.eval.run_retrieval_eval import is_hit
from CS2_PolicyLens.search import (
    apply_lexical_rerank,
    clean_preview_text,
)
from CS2_PolicyLens.src.config import config
from CS2_PolicyLens.src.embeddings import EmbeddingEngine
from CS2_PolicyLens.src.indexing_pipeline import query_policy_corpus

EVAL_DIR = Path(__file__).resolve().parent
QUESTIONS_FILE = EVAL_DIR / "questions.csv"
OUTPUT_METRICS_FILE = EVAL_DIR / "enhancement_comparison_metrics.json"


def run_evaluation() -> dict[str, Any]:
    with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
        questions = list(csv.DictReader(f))

    engine = EmbeddingEngine()

    configs = [
        "baseline_dense",
        "dense_lexical_boost",
        "dense_lexical_denoised",
    ]

    metrics: dict[str, dict[str, Any]] = {
        cfg: {
            "r_at_3": 0,
            "r_at_5": 0,
            "r_at_10": 0,
            "mrr_sum": 0.0,
            "ranks": {},
        }
        for cfg in configs
    }

    per_question_results: list[dict[str, Any]] = []

    for q in questions:
        qid = q["question_id"]
        query = q["question"]
        gold_doc = q["gold_document_id"]
        gold_page = int(q["gold_page_number"])
        gold_text = q.get("gold_evidence_text", "")

        # Candidate pool of 15 chunks
        raw_hits = query_policy_corpus(
            query=query,
            collection_name="policylens_structure",
            top_k=15,
            embedding_engine=engine,
        )

        # 1. Baseline Dense
        rank_base = None
        for idx, h in enumerate(raw_hits[:10], 1):
            if is_hit(h, gold_doc, gold_page, gold_text):
                rank_base = idx
                break

        # 2. Dense + Lexical Boost
        reranked_lex = apply_lexical_rerank(
            hits=raw_hits,
            query=query,
            denoise_text=False,
            boost_weight=0.03,
        )
        rank_lex = None
        for idx, h in enumerate(reranked_lex[:10], 1):
            if is_hit(h, gold_doc, gold_page, gold_text):
                rank_lex = idx
                break

        # 3. Dense + Lexical Boost + Masthead Denoising
        reranked_denoised = apply_lexical_rerank(
            hits=raw_hits,
            query=query,
            denoise_text=True,
            boost_weight=0.03,
        )
        rank_denoised = None
        for idx, h in enumerate(reranked_denoised[:10], 1):
            if is_hit(h, gold_doc, gold_page, gold_text):
                rank_denoised = idx
                break

        ranks_map = {
            "baseline_dense": rank_base,
            "dense_lexical_boost": rank_lex,
            "dense_lexical_denoised": rank_denoised,
        }

        for cfg, r in ranks_map.items():
            metrics[cfg]["ranks"][qid] = r
            if r is not None:
                metrics[cfg]["mrr_sum"] += 1.0 / r
                if r <= 3:
                    metrics[cfg]["r_at_3"] += 1
                if r <= 5:
                    metrics[cfg]["r_at_5"] += 1
                if r <= 10:
                    metrics[cfg]["r_at_10"] += 1

        per_question_results.append({
            "question_id": qid,
            "question": query,
            "gold_doc": gold_doc,
            "gold_page": gold_page,
            "rank_baseline": rank_base,
            "rank_lexical": rank_lex,
            "rank_denoised": rank_denoised,
            "change": "SAME" if rank_base == rank_lex else ("UP" if rank_lex < rank_base else "DOWN"),
        })

    N = len(questions)
    summary: dict[str, Any] = {
        "benchmark_questions": N,
        "configurations": {},
        "focus_questions": {
            "Q06": {cfg: metrics[cfg]["ranks"]["Q06"] for cfg in configs},
            "Q10": {cfg: metrics[cfg]["ranks"]["Q10"] for cfg in configs},
            "Q23": {cfg: metrics[cfg]["ranks"]["Q23"] for cfg in configs},
        },
        "per_question": per_question_results,
    }

    for cfg in configs:
        summary["configurations"][cfg] = {
            "recall_at_3": round(metrics[cfg]["r_at_3"] / N, 4),
            "recall_at_5": round(metrics[cfg]["r_at_5"] / N, 4),
            "recall_at_10": round(metrics[cfg]["r_at_10"] / N, 4),
            "mrr": round(metrics[cfg]["mrr_sum"] / N, 4),
            "raw_counts": {
                "top3": metrics[cfg]["r_at_3"],
                "top5": metrics[cfg]["r_at_5"],
                "top10": metrics[cfg]["r_at_10"],
            },
        }

    # Evaluate 3 NPA queries
    npa_queries = [
        ("Query 1", "What are substandard, doubtful, and loss assets in asset classification?"),
        ("Query 2", "When does a credit facility get classified as a non-performing asset or out of order?"),
        ("Query 3", "What is the definition of a non-performing asset in IRAC directions?"),
    ]

    npa_results = []
    for q_label, query in npa_queries:
        raw_hits = query_policy_corpus(
            query=query,
            collection_name="policylens_v1",
            top_k=25,
            embedding_engine=engine,
        )
        reranked = apply_lexical_rerank(raw_hits, query, denoise_text=True)

        npa_results.append({
            "label": q_label,
            "query": query,
            "before_top3": [
                {
                    "rank": i,
                    "doc_id": h["document_id"],
                    "page": h.get("page_number"),
                    "score": round(float(h.get("score", 0.0)), 4),
                    "preview": clean_preview_text(h.get("text", ""), max_length=150),
                }
                for i, h in enumerate(raw_hits[:3], 1)
            ],
            "after_top3": [
                {
                    "rank": i,
                    "doc_id": h["document_id"],
                    "page": h.get("page_number"),
                    "score": round(float(h["score"]), 4),
                    "base_score": round(float(h["base_score"]), 4),
                    "boost": round(float(h["lexical_boost"]), 4),
                    "preview": clean_preview_text(h.get("text", ""), max_length=150),
                }
                for i, h in enumerate(reranked[:3], 1)
            ],
        })

    summary["npa_case_studies"] = npa_results

    with open(OUTPUT_METRICS_FILE, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return summary


if __name__ == "__main__":
    res = run_evaluation()
    print("Execution complete. Summary generated at:", OUTPUT_METRICS_FILE)

