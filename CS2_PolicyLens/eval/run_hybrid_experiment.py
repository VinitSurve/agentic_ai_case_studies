"""
PolicyLens (Case Study 2) – Controlled Hybrid Candidate Retrieval & Strategy Comparison

Evaluates 5 retrieval configurations:
1. Dense baseline
2. Dense + Config 4 reranking
3. Dense + Query Expansion + Config 4
4. Hybrid (Dense + Lexical Candidates) + Config 4
5. Hybrid (Dense + Lexical Candidates + Query Expansion) + Config 4

Evaluates both:
- 25-question benchmark on policylens_structure
- 3 NPA queries on policylens_v1
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

repo_root = Path(__file__).resolve().parent.parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from CS2_PolicyLens.eval.run_retrieval_eval import is_hit
from CS2_PolicyLens.search import (
    STOPWORDS,
    clean_masthead,
    clean_preview_text,
)
from CS2_PolicyLens.src.config import config
from CS2_PolicyLens.src.embeddings import EmbeddingEngine
from CS2_PolicyLens.src.indexing_pipeline import (
    get_chroma_collection,
    query_policy_corpus,
)
from CS2_PolicyLens.src.version_registry import get_database_connection

DOMAIN_STOPWORDS = {
    "bank", "banks", "directions", "direction", "circular", "circulars",
    "reserve", "india", "clause", "clauses", "annex", "annexure",
}

REGULATORY_SYNONYMS = {
    "irac": "Income Recognition and Asset Classification",
    "npa": "Non-Performing Asset",
    "npas": "Non-Performing Assets",
    "non-performing asset": "NPA loan advance overdue",
    "io": "Internal Ombudsman",
    "kyc": "Know Your Customer",
    "ckycrr": "Central KYC Records Registry",
    "vipv": "Video In-Person Verification",
    "ppo": "Pension Payment Order",
    "od/cc": "Overdraft Cash Credit",
}


def expand_query_text(query: str) -> str:
    """Applies domain-principled regulatory synonym and acronym expansion."""
    q_lower = query.lower()
    expansions: list[str] = []
    for term, exp in REGULATORY_SYNONYMS.items():
        if re.search(r"\b" + re.escape(term) + r"\b", q_lower):
            if exp.lower() not in q_lower:
                expansions.append(exp)
    if expansions:
        return f"{query} ({' '.join(expansions)})"
    return query


def extract_calibrated_terms(query: str) -> tuple[list[str], list[str], list[str]]:
    """
    Extracts terms enforcing:
    1. No isolated digits.
    2. Exclude domain stopwords.
    3. Phrases bounded only by non-stopwords.
    4. Exact quoted phrases preserved.
    """
    q_norm = query.lower()
    quotes = [q.strip() for q in re.findall(r'\"([^\"]+)\"', q_norm) if q.strip()]

    raw_tokens = re.findall(r"[a-zA-Z0-9_\-\.]+", q_norm)
    salient_words: list[str] = []
    for w in raw_tokens:
        clean = re.sub(r"^[^\w]+|[^\w]+$", "", w)
        if not clean or clean in STOPWORDS or clean in DOMAIN_STOPWORDS or clean.isdigit():
            continue
        if len(clean) >= 3 or (any(c.isdigit() for c in clean) and len(clean) >= 3):
            salient_words.append(clean)

    words_seq = [re.sub(r"^[^\w]+|[^\w]+$", "", w) for w in q_norm.split()]
    words_seq = [w for w in words_seq if w]
    raw_phrases: list[str] = []
    for n in (2, 3):
        for i in range(len(words_seq) - n + 1):
            window = words_seq[i : i + n]
            if window[0] in STOPWORDS or window[-1] in STOPWORDS:
                continue
            if any(w not in STOPWORDS for w in window):
                raw_phrases.append(" ".join(window))

    phrases = sorted(set(raw_phrases), key=lambda x: (len(x.split()), len(x)), reverse=True)
    return sorted(set(salient_words)), phrases, sorted(set(quotes))


def find_non_overlapping_phrase_matches(phrases: list[str], text_lower: str) -> list[str]:
    """Maximal non-overlapping span matching prevents duplicate reward for sub-phrases."""
    sorted_phrases = sorted(phrases, key=lambda p: (len(p.split()), len(p)), reverse=True)
    matched_spans: list[tuple[int, int]] = []
    matched_phrases: list[str] = []
    for phrase in sorted_phrases:
        start = 0
        while True:
            idx = text_lower.find(phrase, start)
            if idx == -1:
                break
            end = idx + len(phrase)
            start = idx + 1
            overlaps = any(not (end <= s or idx >= e) for s, e in matched_spans)
            if not overlaps:
                matched_spans.append((idx, end))
                if phrase not in matched_phrases:
                    matched_phrases.append(phrase)
    return matched_phrases


def apply_config4_rerank(hits: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """Applies Config 4: Domain stopwords excluded, phrase deduplicated, dynamic 10% boost cap."""
    salient_words, phrases, quotes = extract_calibrated_terms(query)
    reranked: list[dict[str, Any]] = []
    for h in hits:
        text = clean_masthead(h.get("text", "")).lower()
        mw = [w for w in salient_words if w in text]
        mp = find_non_overlapping_phrase_matches(phrases, text)
        mq = [q for q in quotes if q in text]

        raw_boost = (len(mw) * 0.010) + (len(mp) * 0.025) + (len(mq) * 0.040)
        base = float(h.get("score", 0.0))
        boost = min(raw_boost, 0.10 * max(base, 0.0))

        h_copy = dict(h)
        h_copy["score"] = base + boost
        h_copy["base_score"] = base
        h_copy["lexical_boost"] = boost
        h_copy["matched_words"] = mw
        h_copy["matched_phrases"] = mp
        reranked.append(h_copy)

    reranked.sort(key=lambda x: x["score"], reverse=True)
    return reranked


def retrieve_hybrid_candidate_pool(
    query: str,
    collection_name: str,
    top_k_dense: int = 20,
    top_k_lexical: int = 20,
    use_expansion: bool = False,
    engine: EmbeddingEngine | None = None,
    chroma_col: Any = None,
    active_filter: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], int, int]:
    """
    Executes hybrid candidate generation:
    1. Dense vector candidate search (with optional query expansion).
    2. High-precision lexical triggers (quotes, multi-word phrases, salient terms).
    3. Candidate deduplication using stable chunk_id.
    4. Exact cosine calculation for lexical-only candidates via stored unit vector dot-product.
    Returns: (deduplicated_candidates, raw_pool_size, dedup_pool_size)
    """
    encoder = engine or EmbeddingEngine()
    search_q = expand_query_text(query) if use_expansion else query
    q_emb = np.array(encoder.encode([search_q])[0])

    # 1. Dense candidate retrieval
    dense_res = chroma_col.query(
        query_embeddings=[q_emb.tolist()],
        n_results=top_k_dense,
        where=active_filter,
    )

    # 2. Extract lexical triggers (supporting punctuation & case variations)
    salient_words, phrases, quotes = extract_calibrated_terms(query)
    raw_triggers = set(quotes)
    for p in phrases:
        # Exclude phrases composed purely of domain stopwords
        if any(w not in DOMAIN_STOPWORDS and not w.isdigit() for w in p.split()):
            raw_triggers.add(p)
            if " " in p:
                raw_triggers.add(p.replace(" ", "-"))
    for w in salient_words:
        if len(w) >= 4 or any(c.isdigit() for c in w):
            raw_triggers.add(w)

    trigger_variants: list[str] = []
    for t in sorted(raw_triggers, key=lambda x: (len(x.split()), len(x)), reverse=True)[:15]:
        trigger_variants.append(t.lower())
        trigger_variants.append(t.title())
        trigger_variants.append(t.upper())

    # De-duplicate trigger variants preserving order
    seen_tv: set[str] = set()
    dedup_triggers: list[str] = []
    for tv in trigger_variants:
        if tv not in seen_tv:
            seen_tv.add(tv)
            dedup_triggers.append(tv)

    # 3. Query ChromaDB lexical matching
    lex_res: dict[str, Any] = {"ids": [], "documents": [], "metadatas": [], "embeddings": []}
    if dedup_triggers:
        where_doc = {"$or": [{"$contains": t} for t in dedup_triggers[:25]]}
        try:
            lex_res = chroma_col.get(
                where=active_filter,
                where_document=where_doc,
                limit=top_k_lexical,
                include=["documents", "metadatas", "embeddings"],
            )
        except Exception:
            pass

    # 4. Merging & Deduplication
    dense_ids = dense_res["ids"][0] if dense_res and dense_res.get("ids") else []
    lex_ids = lex_res.get("ids", [])

    raw_pool_size = len(dense_ids) + len(lex_ids)
    candidates: dict[str, dict[str, Any]] = {}

    for cid, doc, meta, dist in zip(
        dense_ids,
        dense_res["documents"][0],
        dense_res["metadatas"][0],
        dense_res["distances"][0],
    ):
        candidates[cid] = {
            "chunk_id": cid,
            "document_id": meta.get("document_id"),
            "text": doc,
            "score": round(1.0 - dist, 4) if dist is not None else 0.0,
            "page_number": meta.get("page_number"),
            "section_heading": meta.get("section_heading"),
            "source": "dense",
            "metadata": meta,
        }

    for cid, doc, meta, emb in zip(
        lex_ids,
        lex_res["documents"],
        lex_res["metadatas"],
        lex_res["embeddings"],
    ):
        if cid in candidates:
            candidates[cid]["source"] = "both"
        else:
            cos = float(np.dot(q_emb, emb))
            candidates[cid] = {
                "chunk_id": cid,
                "document_id": meta.get("document_id"),
                "text": doc,
                "score": round(cos, 4),
                "page_number": meta.get("page_number"),
                "section_heading": meta.get("section_heading"),
                "source": "lexical",
                "metadata": meta,
            }

    dedup_pool_size = len(candidates)
    return list(candidates.values()), raw_pool_size, dedup_pool_size


def run_comprehensive_experiment() -> dict[str, Any]:
    with open(config.BASE_DIR / "eval" / "questions.csv", "r", encoding="utf-8") as f:
        benchmark_questions = list(csv.DictReader(f))

    engine = EmbeddingEngine()
    db_conn = get_database_connection(config.REGISTRY_DB_PATH)

    # Preload active fingerprints for both collections
    cursor = db_conn.cursor()
    cursor.execute("SELECT active_fingerprint FROM document_registry WHERE collection_name = 'policylens_structure'")
    struct_fps = [r[0] for r in cursor.fetchall() if r[0]]
    struct_filter = {"$and": [{"collection_name": "policylens_structure"}, {"index_fingerprint": {"$in": struct_fps}}]}

    cursor.execute("SELECT active_fingerprint FROM document_registry WHERE collection_name = 'policylens_v1'")
    v1_fps = [r[0] for r in cursor.fetchall() if r[0]]
    v1_filter = {"$and": [{"collection_name": "policylens_v1"}, {"index_fingerprint": {"$in": v1_fps}}]}

    col_struct = get_chroma_collection("policylens_structure")
    col_v1 = get_chroma_collection("policylens_v1")

    configs = [
        "1. Dense Baseline",
        "2. Dense + Config 4",
        "3. Dense + Query Expansion + Config 4",
        "4. Hybrid (Dense + Lexical) + Config 4",
        "5. Hybrid + Query Expansion + Config 4",
    ]

    metrics: dict[str, dict[str, Any]] = {
        cfg: {
            "r3": 0, "r5": 0, "r10": 0, "mrr_sum": 0.0,
            "latencies": [], "ranks": {}, "raw_sizes": [], "dedup_sizes": [],
        }
        for cfg in configs
    }

    print("Evaluating 25-Question Benchmark across 5 configurations...")
    for q in benchmark_questions:
        qid = q["question_id"]
        query = q["question"]
        gold_doc = q["gold_document_id"]
        gold_page = int(q["gold_page_number"])
        gold_text = q.get("gold_evidence_text", "")

        # 1. Dense Baseline
        t0 = time.perf_counter()
        raw_dense = query_policy_corpus(query, "policylens_structure", top_k=20, embedding_engine=engine)
        dt1 = (time.perf_counter() - t0) * 1000
        metrics["1. Dense Baseline"]["latencies"].append(dt1)
        r1 = next((i for i, h in enumerate(raw_dense[:10], 1) if is_hit(h, gold_doc, gold_page, gold_text)), None)
        metrics["1. Dense Baseline"]["ranks"][qid] = r1

        # 2. Dense + Config 4
        t0 = time.perf_counter()
        hits2 = apply_config4_rerank(raw_dense, query)
        dt2 = (time.perf_counter() - t0) * 1000 + dt1
        metrics["2. Dense + Config 4"]["latencies"].append(dt2)
        r2 = next((i for i, h in enumerate(hits2[:10], 1) if is_hit(h, gold_doc, gold_page, gold_text)), None)
        metrics["2. Dense + Config 4"]["ranks"][qid] = r2

        # 3. Dense + Query Expansion + Config 4
        t0 = time.perf_counter()
        exp_q = expand_query_text(query)
        dense_exp = query_policy_corpus(exp_q, "policylens_structure", top_k=20, embedding_engine=engine)
        hits3 = apply_config4_rerank(dense_exp, exp_q)
        dt3 = (time.perf_counter() - t0) * 1000
        metrics["3. Dense + Query Expansion + Config 4"]["latencies"].append(dt3)
        r3 = next((i for i, h in enumerate(hits3[:10], 1) if is_hit(h, gold_doc, gold_page, gold_text)), None)
        metrics["3. Dense + Query Expansion + Config 4"]["ranks"][qid] = r3

        # 4. Hybrid (Dense + Lexical) + Config 4
        t0 = time.perf_counter()
        cand4, raw_sz4, dedup_sz4 = retrieve_hybrid_candidate_pool(
            query=query, collection_name="policylens_structure",
            top_k_dense=20, top_k_lexical=20, use_expansion=False,
            engine=engine, chroma_col=col_struct, active_filter=struct_filter,
        )
        hits4 = apply_config4_rerank(cand4, query)
        dt4 = (time.perf_counter() - t0) * 1000
        metrics["4. Hybrid (Dense + Lexical) + Config 4"]["latencies"].append(dt4)
        metrics["4. Hybrid (Dense + Lexical) + Config 4"]["raw_sizes"].append(raw_sz4)
        metrics["4. Hybrid (Dense + Lexical) + Config 4"]["dedup_sizes"].append(dedup_sz4)
        r4 = next((i for i, h in enumerate(hits4[:10], 1) if is_hit(h, gold_doc, gold_page, gold_text)), None)
        metrics["4. Hybrid (Dense + Lexical) + Config 4"]["ranks"][qid] = r4

        # 5. Hybrid + Query Expansion + Config 4
        t0 = time.perf_counter()
        cand5, raw_sz5, dedup_sz5 = retrieve_hybrid_candidate_pool(
            query=query, collection_name="policylens_structure",
            top_k_dense=20, top_k_lexical=20, use_expansion=True,
            engine=engine, chroma_col=col_struct, active_filter=struct_filter,
        )
        hits5 = apply_config4_rerank(cand5, exp_q)
        dt5 = (time.perf_counter() - t0) * 1000
        metrics["5. Hybrid + Query Expansion + Config 4"]["latencies"].append(dt5)
        metrics["5. Hybrid + Query Expansion + Config 4"]["raw_sizes"].append(raw_sz5)
        metrics["5. Hybrid + Query Expansion + Config 4"]["dedup_sizes"].append(dedup_sz5)
        r5 = next((i for i, h in enumerate(hits5[:10], 1) if is_hit(h, gold_doc, gold_page, gold_text)), None)
        metrics["5. Hybrid + Query Expansion + Config 4"]["ranks"][qid] = r5

        for cfg, r in zip(configs, [r1, r2, r3, r4, r5]):
            if r is not None:
                metrics[cfg]["mrr_sum"] += 1.0 / r
                if r <= 3: metrics[cfg]["r3"] += 1
                if r <= 5: metrics[cfg]["r5"] += 1
                if r <= 10: metrics[cfg]["r10"] += 1

    # Candidate recall on policylens_structure
    cand_recalls = {20: 0, 50: 0, 100: 0}
    for q in benchmark_questions:
        hits = query_policy_corpus(q["question"], "policylens_structure", top_k=100, embedding_engine=engine)
        for k in [20, 50, 100]:
            if any(is_hit(h, q["gold_document_id"], int(q["gold_page_number"]), q.get("gold_evidence_text", "")) for h in hits[:k]):
                cand_recalls[k] += 1

    N = len(benchmark_questions)
    benchmark_summary: dict[str, Any] = {
        "candidate_recalls": {
            "R@20": cand_recalls[20] / N,
            "R@50": cand_recalls[50] / N,
            "R@100": cand_recalls[100] / N,
        },
        "configurations": {},
        "regressions": {},
    }

    for cfg in configs:
        regressed = [qid for qid, r in metrics[cfg]["ranks"].items() if metrics["1. Dense Baseline"]["ranks"][qid] is not None and (r is None or r > metrics["1. Dense Baseline"]["ranks"][qid])]
        benchmark_summary["regressions"][cfg] = regressed
        benchmark_summary["configurations"][cfg] = {
            "recall_at_3": round(metrics[cfg]["r3"] / N, 4),
            "recall_at_5": round(metrics[cfg]["r5"] / N, 4),
            "recall_at_10": round(metrics[cfg]["r10"] / N, 4),
            "mrr": round(metrics[cfg]["mrr_sum"] / N, 4),
            "avg_latency_ms": round(sum(metrics[cfg]["latencies"]) / N, 2),
            "q23_rank": metrics[cfg]["ranks"]["Q23"],
            "avg_raw_pool": round(sum(metrics[cfg]["raw_sizes"]) / N, 1) if metrics[cfg]["raw_sizes"] else 20.0,
            "avg_dedup_pool": round(sum(metrics[cfg]["dedup_sizes"]) / N, 1) if metrics[cfg]["dedup_sizes"] else 20.0,
        }

    # Evaluate NPA Queries on policylens_v1
    npa_queries = [
        ("NPA Query 1", "What are substandard, doubtful, and loss assets in asset classification?"),
        ("NPA Query 2", "When does a credit facility get classified as a non-performing asset or out of order?"),
        ("NPA Query 3", "What is the definition of a non-performing asset in IRAC directions?"),
    ]

    npa_results = []
    for label, q_text in npa_queries:
        q_dict: dict[str, Any] = {"label": label, "query": q_text, "configs": {}}
        for cfg in configs:
            t0 = time.perf_counter()
            if cfg == "1. Dense Baseline":
                res = query_policy_corpus(q_text, "policylens_v1", top_k=25, embedding_engine=engine)
                hits = res
                raw_sz, dedup_sz = 25, 25
            elif cfg == "2. Dense + Config 4":
                res = query_policy_corpus(q_text, "policylens_v1", top_k=25, embedding_engine=engine)
                hits = apply_config4_rerank(res, q_text)
                raw_sz, dedup_sz = 25, 25
            elif cfg == "3. Dense + Query Expansion + Config 4":
                exp_q = expand_query_text(q_text)
                res = query_policy_corpus(exp_q, "policylens_v1", top_k=25, embedding_engine=engine)
                hits = apply_config4_rerank(res, exp_q)
                raw_sz, dedup_sz = 25, 25
            elif cfg == "4. Hybrid (Dense + Lexical) + Config 4":
                cand, raw_sz, dedup_sz = retrieve_hybrid_candidate_pool(
                    query=q_text, collection_name="policylens_v1",
                    top_k_dense=25, top_k_lexical=25, use_expansion=False,
                    engine=engine, chroma_col=col_v1, active_filter=v1_filter,
                )
                hits = apply_config4_rerank(cand, q_text)
            elif cfg == "5. Hybrid + Query Expansion + Config 4":
                exp_q = expand_query_text(q_text)
                cand, raw_sz, dedup_sz = retrieve_hybrid_candidate_pool(
                    query=q_text, collection_name="policylens_v1",
                    top_k_dense=25, top_k_lexical=25, use_expansion=True,
                    engine=engine, chroma_col=col_v1, active_filter=v1_filter,
                )
                hits = apply_config4_rerank(cand, exp_q)

            dt = (time.perf_counter() - t0) * 1000

            rank_s8 = next((i for i, h in enumerate(hits, 1) if h.get("chunk_id") == "rbi_asset_class_irac_2026_struct_0008"), None)
            rank_s9 = next((i for i, h in enumerate(hits, 1) if h.get("chunk_id") == "rbi_asset_class_irac_2026_struct_0009"), None)

            q_dict["configs"][cfg] = {
                "latency_ms": round(dt, 2),
                "raw_pool_size": raw_sz,
                "dedup_pool_size": dedup_sz,
                "clause8_struct_0008_rank": rank_s8,
                "clause8_struct_0009_rank": rank_s9,
                "top3": [
                    {
                        "rank": i,
                        "doc_id": h["document_id"],
                        "chunk_id": h.get("chunk_id"),
                        "page": h.get("page_number"),
                        "score": round(float(h.get("score", 0.0)), 4),
                        "base_score": round(float(h.get("base_score", h.get("score", 0.0))), 4),
                        "boost": round(float(h.get("lexical_boost", 0.0)), 4),
                        "source": h.get("source", "dense"),
                        "preview": clean_preview_text(h.get("text", ""), max_length=120),
                    }
                    for i, h in enumerate(hits[:3], 1)
                ],
            }
        npa_results.append(q_dict)

    full_output = {
        "benchmark_summary": benchmark_summary,
        "npa_results": npa_results,
    }

    out_file = config.BASE_DIR / "eval" / "hybrid_experiment_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(full_output, f, indent=2)

    db_conn.close()
    return full_output


if __name__ == "__main__":
    res = run_comprehensive_experiment()
    print("Experiment completed. Results saved to eval/hybrid_experiment_results.json")
