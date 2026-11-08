"""
PolicyLens (Case Study 2) – Phase C End-to-End RAG QA Validation Runner

Evaluates 8 representative categories:
1. Straightforward regulatory fact
2. Regulatory definition (Clause 6(17))
3. Multi-condition regulatory clause (Clause 10)
4. Structured table / circular reference
5. Multi-chunk regulatory criteria (Clause 8 items 1-8)
6. Particular issuer governance criteria (RBI IO)
7. Insufficient evidence / out-of-scope query
8. Ambiguous regulatory query

Evaluates for each question:
- Factual grounding in retrieved source text
- Correct document ID and page number citations
- Absence of hallucination
- Proper insufficient evidence admission
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

repo_root = Path(__file__).resolve().parent.parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from CS2_PolicyLens.src.config import config
from CS2_PolicyLens.src.rag_qa import RegulatoryQAEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("RAG_QA_Eval")

EVAL_SUITE = [
    {
        "category": "1. Straightforward Regulatory Fact",
        "question": "In Annex 1 of the agency bank master direction, which agency bank is listed under serial number 2?",
        "collection": "policylens_structure",
        "top_k": 5,
        "gold_doc": "rbi_agency_comm_2026",
        "gold_page": 16,
        "key_facts": ["Bandhan Bank", "Axis Bank", "Annex 1"],
        "expect_insufficient": False,
    },
    {
        "category": "2. Definition (IRAC Clause 6(17))",
        "question": "Under IRAC directions, what is the definition of an out of order overdraft or cash credit account?",
        "collection": "policylens_v1",
        "top_k": 5,
        "gold_doc": "rbi_asset_class_irac_2026",
        "gold_page": 7,
        "key_facts": ["continuous", "excess of the sanctioned limit", "no credits", "cover the interest", "ninety days"],
        "expect_insufficient": False,
    },
    {
        "category": "3. Multi-condition Regulatory Clause (IRAC Clause 10)",
        "question": "What are the asset classification norms for substandard, doubtful, and loss assets under IRAC directions?",
        "collection": "policylens_v1",
        "top_k": 5,
        "gold_doc": "rbi_asset_class_irac_2026",
        "gold_page": 16,
        "key_facts": ["substandard", "twelve months", "doubtful", "loss asset", "uncollectible"],
        "expect_insufficient": False,
    },
    {
        "category": "4. Table / Structured Provision",
        "question": "What is the circular reference number of the repealed instruction dated 14.10.2009 for pension withdrawal facilities through public sector banks?",
        "collection": "policylens_structure",
        "top_k": 5,
        "gold_doc": "rbi_pension_2026",
        "gold_page": 19,
        "key_facts": ["DGBA", "3194", "14.10.2009"],
        "expect_insufficient": False,
    },
    {
        "category": "5. Multi-chunk Regulatory Criteria (IRAC Clause 8)",
        "question": "What are the specific conditions under Clause 8 of IRAC directions under which a financial asset is classified as an NPA?",
        "collection": "policylens_v1",
        "top_k": 6,
        "gold_doc": "rbi_asset_class_irac_2026",
        "gold_page": [8, 9, 10],
        "key_facts": ["overdue for a period of more than ninety days", "term loan", "out of order", "crop season", "credit card"],
        "expect_insufficient": False,
    },
    {
        "category": "6. Particular Issuer Criteria (RBI Internal Ombudsman)",
        "question": "What are the governance standards and fit and proper criteria specified by RBI for appointment of an Internal Ombudsman in commercial banks?",
        "collection": "policylens_structure",
        "top_k": 5,
        "gold_doc": "rbi_io_comm_2026",
        "gold_page": [3, 4],
        "key_facts": ["Internal Ombudsman", "Commercial Banks", "tenure", "audit"],
        "expect_insufficient": False,
    },
    {
        "category": "7. Insufficient Evidence / Out of Scope",
        "question": "What is the maximum penalty in rupees prescribed by SEBI for insider trading violations by mutual fund trustees under the 2026 directions?",
        "collection": "policylens_v1",
        "top_k": 5,
        "gold_doc": None,
        "gold_page": None,
        "key_facts": ["do not provide sufficient evidence"],
        "expect_insufficient": True,
    },
    {
        "category": "8. Ambiguous Regulatory Query",
        "question": "When does a credit facility become non-performing?",
        "collection": "policylens_v1",
        "top_k": 5,
        "gold_doc": "rbi_asset_class_irac_2026",
        "gold_page": [8, 9, 10],
        "key_facts": ["depends on", "term loan", "out of order", "90 days"],
        "expect_insufficient": False,
    },
]


def run_evaluation() -> dict[str, Any]:
    qa_engine = RegulatoryQAEngine()
    results = []

    for item in EVAL_SUITE:
        cat = item["category"]
        q = item["question"]
        col = item["collection"]
        top_k = item["top_k"]

        logger.info("Evaluating: %s...", cat)
        t0 = time.perf_counter()
        res = qa_engine.answer_question(
            query=q,
            collection_name=col,
            top_k=top_k,
            use_hybrid=True,
            use_rerank=True,
        )
        latency_sec = time.perf_counter() - t0

        answer = res.get("answer", "")
        sources = res.get("sources", [])
        status = res.get("status", "unknown")
        llm = res.get("llm_used", "none")

        # Validation checks
        ans_lower = answer.lower()
        if item["expect_insufficient"]:
            grounded = "sufficient evidence" in ans_lower or "not provide sufficient evidence" in ans_lower
            citation_ok = True
        else:
            # Check key facts presence
            facts_found = [f for f in item["key_facts"] if f.lower() in ans_lower]
            grounded = len(facts_found) >= min(2, len(item["key_facts"]))

            # Check gold doc and page citation
            doc_cited = any(item["gold_doc"] in str(s.get("document_id", "")) for s in sources) if item["gold_doc"] else False
            target_pages = item["gold_page"] if isinstance(item["gold_page"], list) else [item["gold_page"]]
            page_cited = any(s.get("page_number") in target_pages for s in sources) if item["gold_page"] else False
            citation_ok = doc_cited and page_cited

        entry = {
            "category": cat,
            "question": q,
            "collection": col,
            "latency_seconds": round(latency_sec, 3),
            "status": status,
            "llm_used": llm,
            "answer": answer,
            "sources_count": len(sources),
            "sources": sources,
            "evaluation": {
                "factually_grounded": grounded,
                "citation_correct": citation_ok,
                "admitted_insufficient": "not provide sufficient evidence" in ans_lower if item["expect_insufficient"] else None,
            },
        }
        results.append(entry)
        logger.info("  Result for %s: Grounded=%s, CitationOK=%s, Latency=%.2fs", cat, grounded, citation_ok, latency_sec)

    summary = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_questions": len(results),
        "grounded_count": sum(1 for r in results if r["evaluation"]["factually_grounded"]),
        "citation_ok_count": sum(1 for r in results if r["evaluation"]["citation_correct"]),
        "results": results,
    }

    out_file = config.BASE_DIR / "eval" / "rag_qa_evaluation_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    logger.info("Saved RAG QA evaluation results to %s", out_file)
    return summary


if __name__ == "__main__":
    run_evaluation()
