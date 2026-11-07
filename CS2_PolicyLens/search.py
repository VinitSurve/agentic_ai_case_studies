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
import re
import sys
from pathlib import Path
from typing import Any

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from CS2_PolicyLens.src.config import config
from CS2_PolicyLens.src.indexing_pipeline import (
    get_chroma_collection,
    query_policy_corpus,
)
from CS2_PolicyLens.src.rag_qa import RegulatoryQAEngine
from CS2_PolicyLens.src.version_registry import get_database_connection
import numpy as np

STOPWORDS = {
    'a', 'about', 'above', 'after', 'again', 'against', 'all', 'am', 'an', 'and', 'any', 'are', 'aren',
    'as', 'at', 'be', 'because', 'been', 'before', 'being', 'below', 'between', 'both', 'but', 'by',
    'can', 'could', 'did', 'do', 'does', 'doing', 'down', 'during', 'each', 'few', 'for', 'from',
    'further', 'had', 'has', 'have', 'having', 'he', 'her', 'here', 'hers', 'herself', 'him',
    'himself', 'his', 'how', 'i', 'if', 'in', 'into', 'is', 'it', 'its', 'itself', 'just', 'me',
    'more', 'most', 'my', 'myself', 'no', 'nor', 'not', 'now', 'of', 'off', 'on', 'once', 'only',
    'or', 'other', 'our', 'ours', 'ourselves', 'out', 'over', 'own', 'same', 'she', 'should', 'so',
    'some', 'such', 'than', 'that', 'the', 'their', 'theirs', 'them', 'themselves', 'then', 'there',
    'these', 'they', 'this', 'those', 'through', 'to', 'too', 'under', 'until', 'up', 'very', 'was',
    'we', 'were', 'what', 'when', 'where', 'which', 'while', 'who', 'whom', 'why', 'with', 'you',
    'your', 'yours', 'yourself', 'yourselves'
}

DOMAIN_STOPWORDS = {
    'bank', 'banks', 'directions', 'direction', 'circular', 'circulars',
    'reserve', 'india', 'clause', 'clauses', 'annex', 'annexure',
}

REGULATORY_SYNONYMS = {
    'irac': 'Income Recognition and Asset Classification',
    'npa': 'Non-Performing Asset',
    'npas': 'Non-Performing Assets',
    'non-performing asset': 'NPA loan advance overdue',
    'io': 'Internal Ombudsman',
    'kyc': 'Know Your Customer',
    'ckycrr': 'Central KYC Records Registry',
    'vipv': 'Video In-Person Verification',
    'ppo': 'Pension Payment Order',
    'od/cc': 'Overdraft Cash Credit',
}

MASTHEAD_PATTERNS = [
    # Full statutory circular / master direction titles
    r'Reserve Bank of India\s*(?:\([^)\n]*\)\s*)?(?:Directions|Master Direction|Master Circular|Circular)[^,\n]*,?\s*202\d',
    r'Securities and Exchange Board of India\s*(?:\([^)\n]*\)\s*)?(?:Directions|Master Direction|Master Circular|Circular)[^,\n]*,?\s*202\d',
    r'Insurance Regulatory and Development Authority(?: of India)?\s*(?:\([^)\n]*\)\s*)?(?:Directions|Master Direction|Master Circular|Circular)[^,\n]*,?\s*202\d',
    # Bilingual masthead banners
    r'भारतीय\s*ǐ?र[जज़]वर्\s*बैंक',
    r'[-_]{2,}\s*RESERVE BANK OF INDIA\s*[-_]{2,}',
    r'^\s*RESERVE BANK OF INDIA\s*$',
    r'^\s*SECURITIES AND EXCHANGE BOARD OF INDIA\s*$',
    r'[-_]{4,}',
]
MASTHEAD_REGEX = re.compile('|'.join(f'(?:{p})' for p in MASTHEAD_PATTERNS), re.IGNORECASE | re.MULTILINE)


def clean_masthead(text: str) -> str:
    """Removes repetitive regulatory circular running headers and decorative banners."""
    return MASTHEAD_REGEX.sub('', text)


def clean_preview_text(text: str, max_length: int = 300) -> str:
    """Formats chunk text for display by stripping mastheads and section breadcrumbs."""
    cleaned = clean_masthead(text)
    lines: list[str] = []
    for line in cleaned.split('\n'):
        line_s = line.strip()
        if not line_s:
            continue
        # Strip breadcrumb lines like [doc_id > section]
        if line_s.startswith('[') and (' > ' in line_s or line_s.endswith(']')):
            continue
        lines.append(line_s)
    preview = ' '.join(lines[:4])
    preview = re.sub(r'\s+', ' ', preview).strip()
    if len(preview) > max_length:
        preview = preview[:max_length - 3] + '...'
    return preview


def expand_query_text(query: str) -> str:
    """Expands regulatory acronyms and synonyms in a principled manner."""
    q_lower = query.lower()
    expansions: list[str] = []
    for term, exp in REGULATORY_SYNONYMS.items():
        if re.search(r'\b' + re.escape(term) + r'\b', q_lower):
            if exp.lower() not in q_lower:
                expansions.append(exp)
    if expansions:
        return f"{query} ({' '.join(expansions)})"
    return query


def extract_salient_terms(query: str) -> tuple[list[str], list[str], list[str]]:
    """
    Extracts calibrated salient terms, multi-word n-grams, and quoted phrases.
    Enforces:
    1. No isolated digits.
    2. Exclusion of domain stopwords from single-word matches.
    3. Phrases bounded only by non-stopwords.
    4. Exact quoted phrases preserved.
    Returns (salient_words, phrases, quotes).
    """
    q_norm = query.lower()
    quotes = [q.strip() for q in re.findall(r'\"([^\"]+)\"', q_norm) if q.strip()]

    raw_tokens = re.findall(r'[a-zA-Z0-9_\-\.]+', q_norm)
    salient_words: list[str] = []
    for w in raw_tokens:
        clean = re.sub(r'^[^\w]+|[^\w]+$', '', w)
        if not clean or clean in STOPWORDS or clean in DOMAIN_STOPWORDS or clean.isdigit():
            continue
        if len(clean) >= 3 or (any(c.isdigit() for c in clean) and len(clean) >= 3):
            salient_words.append(clean)

    TRIVIAL_LEADING_STOPWORDS = STOPWORDS - {'out', 'off', 'over', 'under', 'further', 'same'}
    words_seq = [re.sub(r'^[^\w]+|[^\w]+$', '', w) for w in q_norm.split()]
    words_seq = [w for w in words_seq if w]
    raw_phrases: list[str] = []
    for n in (2, 3):
        for i in range(len(words_seq) - n + 1):
            window = words_seq[i:i+n]
            if window[0] in TRIVIAL_LEADING_STOPWORDS or window[-1] in STOPWORDS:
                continue
            if any(w not in STOPWORDS for w in window):
                raw_phrases.append(' '.join(window))

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


def apply_lexical_rerank(
    hits: list[dict[str, Any]],
    query: str,
    denoise_text: bool = True,
    boost_weight: float = 0.025,
    max_boost_ratio: float = 0.10,
    fixed_cap: float | None = None,
    max_boost: float | None = None,
) -> list[dict[str, Any]]:
    """
    Applies calibrated Config 4 lexical reranking to vector retrieval candidates:
    - Domain stopwords excluded from single-word matches.
    - No isolated digits rewarded.
    - Non-overlapping phrase deduplication.
    - Dynamic boost cap proportional to base cosine score (default: 10%).
    """
    if fixed_cap is None and max_boost is not None:
        fixed_cap = max_boost
    salient_words, phrases, quotes = extract_salient_terms(query)
    reranked: list[dict[str, Any]] = []
    for h in hits:
        text = h.get('text', '')
        if denoise_text:
            text = clean_masthead(text)
        text_lower = text.lower()
        matched_words = [w for w in salient_words if w in text_lower]
        matched_phrases = find_non_overlapping_phrase_matches(phrases, text_lower)
        matched_quotes = [q for q in quotes if q in text_lower]

        raw_boost = (len(matched_words) * 0.010) + (len(matched_phrases) * boost_weight) + (len(matched_quotes) * 0.040)
        base_score = float(h.get('score', 0.0))

        if fixed_cap is not None:
            lex_boost = min(raw_boost, fixed_cap)
        else:
            lex_boost = min(raw_boost, max_boost_ratio * max(base_score, 0.0))

        final_score = base_score + lex_boost

        h_copy = dict(h)
        h_copy['score'] = final_score
        h_copy['base_score'] = base_score
        h_copy['lexical_boost'] = lex_boost
        h_copy['lexical_matches'] = {
            'words': matched_words,
            'phrases': matched_phrases,
            'quotes': matched_quotes,
        }
        reranked.append(h_copy)

    reranked.sort(key=lambda x: x['score'], reverse=True)
    return reranked


def retrieve_hybrid_candidates(
    query: str,
    collection_name: str = 'policylens_structure',
    top_k_dense: int = 20,
    top_k_lexical: int = 20,
    use_expansion: bool = False,
    active_doc_filter: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], int, int]:
    """
    Generates hybrid candidates by merging dense vector search and ChromaDB lexical matching.
    Returns: (deduplicated_candidate_list, raw_pool_count, dedup_pool_count)
    """
    from CS2_PolicyLens.src.embeddings import EmbeddingEngine
    engine = EmbeddingEngine()
    db_file = config.REGISTRY_DB_PATH
    conn = get_database_connection(db_file)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT active_fingerprint FROM document_registry WHERE collection_name = ?",
        (collection_name,),
    )
    active_fps = [r[0] for r in cursor.fetchall() if r[0]]
    conn.close()

    if not active_fps:
        return [], 0, 0

    base_filter: dict[str, Any] = {
        "$and": [
            {"collection_name": collection_name},
            {"index_fingerprint": {"$in": active_fps}},
        ]
    }
    if active_doc_filter:
        base_filter = {"$and": [base_filter, active_doc_filter]}

    chroma_col = get_chroma_collection(collection_name)
    search_q = expand_query_text(query) if use_expansion else query
    q_emb = np.array(engine.encode([search_q])[0])

    # 1. Dense candidates
    dense_res = chroma_col.query(
        query_embeddings=[q_emb.tolist()],
        n_results=top_k_dense,
        where=base_filter,
    )

    # 2. Extract lexical triggers (supporting case & punctuation variations)
    salient_words, phrases, quotes = extract_salient_terms(query)
    raw_triggers = set(quotes)
    for p in phrases:
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

    seen_tv: set[str] = set()
    dedup_triggers: list[str] = []
    for tv in trigger_variants:
        if tv not in seen_tv:
            seen_tv.add(tv)
            dedup_triggers.append(tv)

    lex_res: dict[str, Any] = {"ids": [], "documents": [], "metadatas": [], "embeddings": []}
    if dedup_triggers:
        where_doc = {"$or": [{"$contains": t} for t in dedup_triggers[:25]]}
        try:
            lex_res = chroma_col.get(
                where=base_filter,
                where_document=where_doc,
                limit=top_k_lexical,
                include=["documents", "metadatas", "embeddings"],
            )
        except Exception:
            pass

    dense_ids = dense_res["ids"][0] if dense_res and dense_res.get("ids") else []
    lex_ids = lex_res.get("ids", [])
    raw_pool_count = len(dense_ids) + len(lex_ids)

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

    dedup_pool_count = len(candidates)
    return list(candidates.values()), raw_pool_count, dedup_pool_count


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
    parser.add_argument(
        "--hybrid",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use hybrid retrieval (dense + lexical triggers) for candidate selection (default: True, disable with --no-hybrid)",
    )
    parser.add_argument(
        "--expand",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Apply domain-principled regulatory synonym and acronym query expansion (default: False)",
    )
    parser.add_argument(
        "--rerank",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Apply Config 4 lexical boost to dense/hybrid candidates (default: True, disable with --no-rerank)",
    )
    parser.add_argument(
        "--denoise",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Strip repetitive circular mastheads in formatted preview (default: True, disable with --no-denoise)",
    )
    parser.add_argument(
        "--boost-weight",
        "--boost_weight",
        type=float,
        default=0.025,
        dest="boost_weight",
        help="Weight multiplier for lexical phrase matching boost (default: 0.025)",
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
        raw_pool_sz, dedup_pool_sz = 0, 0

        if args.hybrid:
            doc_filter = None
            if allowed_doc_ids is not None:
                doc_filter = {"document_id": {"$in": list(allowed_doc_ids)}}
            raw_candidates, raw_pool_sz, dedup_pool_sz = retrieve_hybrid_candidates(
                query=active_query,
                collection_name=target_collection,
                top_k_dense=max(args.top_k * 4, 25),
                top_k_lexical=max(args.top_k * 4, 25),
                use_expansion=args.expand,
                active_doc_filter=doc_filter,
            )
        else:
            search_query = expand_query_text(active_query) if args.expand else active_query
            candidate_k = max(args.top_k * 4, 25) if (args.rerank or allowed_doc_ids) else args.top_k
            raw_candidates = query_policy_corpus(
                query=search_query,
                collection_name=target_collection,
                top_k=candidate_k,
            )
            raw_pool_sz, dedup_pool_sz = len(raw_candidates), len(raw_candidates)

        candidates: list[dict[str, Any]] = []
        for h in raw_candidates:
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

            candidates.append(h)

        if not candidates:
            print("[-] No active indexed content found matching query and filter.")
            return

        # Apply lexical reranking if enabled
        if args.rerank:
            rerank_q = expand_query_text(active_query) if args.expand else active_query
            reranked = apply_lexical_rerank(
                hits=candidates,
                query=rerank_q,
                denoise_text=args.denoise,
                boost_weight=args.boost_weight,
            )
            hits = reranked[:args.top_k]
        else:
            hits = candidates[:args.top_k]

        mode_desc = []
        mode_desc.append("Hybrid Candidates" if args.hybrid else "Dense-Only Candidates")
        if args.expand:
            mode_desc.append("Query Expanded")
        mode_desc.append("Config 4 Rerank" if args.rerank else "Unranked Baseline")
        mode_str = " | ".join(mode_desc)
        pool_str = f" | Pool: {raw_pool_sz} -> {dedup_pool_sz}" if args.hybrid else ""

        print(f"[+] Found {len(hits)} matching chunks (Active Versions Only | {mode_str}{pool_str}):")
        for idx, hit in enumerate(hits, 1):
            if hit.get("lexical_boost") is not None and hit.get("lexical_boost") > 0:
                score_str = f" | Score: {hit['score']:.4f} (Dense: {hit.get('base_score', hit['score']):.4f}, Boost: +{hit['lexical_boost']:.4f})"
            elif hit.get("score") is not None:
                score_str = f" | Cosine Score: {hit['score']:.4f}"
            else:
                score_str = ""

            title_str = hit.get("title") or hit.get("document_id")
            issuer_str = f" ({hit.get('issuer')})" if hit.get("issuer") else ""
            section_str = hit.get("section_heading") or "General"
            page_str = hit.get("page_number", 1)
            src_str = f" [{hit.get('source', 'dense')}]" if hit.get("source") else ""

            print(f"\n--- Result {idx} | {title_str}{issuer_str}{src_str} ---")
            print(f"    Document ID: {hit['document_id']} | Page: {page_str} | Section: {section_str}{score_str}")
            print(f"    Text Preview:")
            body = hit.get("text", "").strip()
            if args.denoise:
                preview = clean_preview_text(body, max_length=300)
            else:
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
