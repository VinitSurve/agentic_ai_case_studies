"""
PolicyLens (Case Study 2) – Entity-Level Retrieval Disambiguation Module

Provides domain-principled regulated-entity recognition and candidate disambiguation
to resolve cross-circular competition among parallel statutory frameworks (e.g. Commercial
Banks vs Small Finance Banks, NBFCs, PPI Issuers, and Credit Information Companies).
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Any, NamedTuple

from CS2_PolicyLens.src.config import config

logger = logging.getLogger(__name__)

# Canonical regulated-entity taxonomy and regex triggers
ENTITY_TAXONOMY: dict[str, list[str]] = {
    "COMMERCIAL_BANK": [
        r"\bcommercial\s+banks?\b",
        r"\bscheduled\s+commercial\s+banks?\b",
    ],
    "SMALL_FINANCE_BANK": [
        r"\bsmall\s+finance\s+banks?\b",
        r"\bsfbs?\b",
    ],
    "NBFC": [
        r"\bnon[\-\s]banking\s+financial\s+compan(?:y|ies)\b",
        r"\bnbfcs?\b",
    ],
    "PPI_ISSUER": [
        r"\bprepaid\s+payment\s+instruments?\b",
        r"\bnon[\-\s]bank\s+ppis?\b",
        r"\bppi\s+issuers?\b",
        r"\bppis?\b",
    ],
    "CREDIT_INFORMATION_COMPANY": [
        r"\bcredit\s+information\s+compan(?:y|ies)\b",
        r"\bcics?\b",
    ],
    "AGENCY_BANK": [
        r"\bagency\s+banks?\b",
    ],
    "PRIMARY_DEALER": [
        r"\bprimary\s+dealers?\b",
    ],
    "MUTUAL_FUND": [
        r"\bmutual\s+funds?\b",
        r"\basset\s+management\s+compan(?:y|ies)\b",
        r"\bamcs?\b",
    ],
    "REIT": [
        r"\breal\s+estate\s+investment\s+trusts?\b",
        r"\breits?\b",
    ],
    "INVIT": [
        r"\binfrastructure\s+investment\s+trusts?\b",
        r"\binvits?\b",
    ],
    "STOCK_EXCHANGE": [
        r"\bstock\s+exchanges?\b",
        r"\bclearing\s+corporations?\b",
    ],
    "INSURER": [
        r"\binsurers?\b",
        r"\binsurance\s+compan(?:y|ies)\b",
    ],
}

# Negative-context disqualifiers for broad abbreviations
ABBREVIATION_NEGATIVE_PATTERNS: dict[str, list[str]] = {
    "PPI_ISSUER": [
        r"\bproducer\s+price\s+index\b",
        r"\bppi\s+inflation\b",
        r"\bproton\s+pump\b",
        r"\bpixels?\s+per\s+inch\b",
        r"\bpayment\s+protection\s+insurance\b",
        r"\bppi\s+index\b",
    ],
    "CREDIT_INFORMATION_COMPANY": [
        r"\bcentral\s+information\s+commission\b",
        r"\bchief\s+information\s+commissioner\b",
        r"\brti\b",
        r"\bright\s+to\s+information\b",
        r"\bcounter\s+intelligence\b",
    ],
    "MUTUAL_FUND": [
        r"\bannual\s+maintenance\s+contract\b",
        r"\bmaintenance\s+contract\b",
        r"\bhardware\s+amc\b",
        r"\bequipment\s+amc\b",
        r"\bamc\s+tender\b",
        r"\bamc\s+services?\b",
        r"\bserver\s+amc\b",
    ],
    "SMALL_FINANCE_BANK": [
        r"\bsan\s+francisco\s+bay\b",
        r"\bsingle\s+family\s+building\b",
        r"\bsfb\s+area\b",
    ],
    "REIT": [
        r"\bre[\-\s]?iterate\b",
    ],
}


class EntityDetectionResult(NamedTuple):
    """
    Structured outcome of query entity intent analysis.
    - entity_type: Canonical entity identifier, or None if ambiguous/none.
    - confidence: 'explicit', 'ambiguous', or 'none'.
    - matched_phrase: The exact substring in the query that triggered detection.
    """
    entity_type: str | None
    confidence: str
    matched_phrase: str | None


def detect_query_entity(query: str) -> EntityDetectionResult:
    """
    Parses a user query for explicit regulated-entity intent.

    Distinguishes:
    1. Explicit entity intent (exactly one entity class matched).
    2. Ambiguous entity intent (multiple conflicting entity classes matched).
    3. No entity intent (zero entity classes matched).

    Filters out broad abbreviations when used in unrelated or negative contexts.
    """
    q_lower = query.lower()
    matches: list[tuple[str, str]] = []

    for etype, patterns in ENTITY_TAXONOMY.items():
        # Check if negative context patterns for this entity class match the query
        if etype in ABBREVIATION_NEGATIVE_PATTERNS:
            if any(re.search(neg, q_lower) for neg in ABBREVIATION_NEGATIVE_PATTERNS[etype]):
                continue

        for pat in patterns:
            m = re.search(pat, q_lower)
            if m:
                matches.append((etype, m.group(0)))
                break

    if len(matches) == 1:
        return EntityDetectionResult(
            entity_type=matches[0][0],
            confidence="explicit",
            matched_phrase=matches[0][1],
        )
    elif len(matches) > 1:
        return EntityDetectionResult(
            entity_type=None,
            confidence="ambiguous",
            matched_phrase=None,
        )
    else:
        return EntityDetectionResult(
            entity_type=None,
            confidence="none",
            matched_phrase=None,
        )


def get_document_entity_type(doc_id: str, title: str = "") -> str | None:
    """
    Resolves a document's statutory regulated-entity class from its title and doc_id.
    Prevents false matches (e.g. distinguishing 'agency commission' from 'commercial bank',
    and ensuring pension documents remain unclassified unless their title explicitly establishes
    an agency bank or other regulated-entity class).
    """
    t_lower = (title or "").lower()
    d_lower = (doc_id or "").lower()

    # 1. High-precision official title matching
    if "commercial bank" in t_lower:
        return "COMMERCIAL_BANK"
    if "small finance bank" in t_lower:
        return "SMALL_FINANCE_BANK"
    if "non-banking financial" in t_lower or "nbfc" in t_lower:
        return "NBFC"
    if "prepaid payment" in t_lower:
        return "PPI_ISSUER"
    if "credit information" in t_lower:
        return "CREDIT_INFORMATION_COMPANY"
    if "agency bank" in t_lower:
        return "AGENCY_BANK"
    if "primary dealer" in t_lower:
        return "PRIMARY_DEALER"
    if "mutual fund" in t_lower or "asset management" in t_lower:
        return "MUTUAL_FUND"
    if "real estate investment trust" in t_lower or "reit" in t_lower:
        return "REIT"
    if "infrastructure investment trust" in t_lower or "invit" in t_lower:
        return "INVIT"
    if "stock exchange" in t_lower or "clearing corporation" in t_lower:
        return "STOCK_EXCHANGE"
    if "insurer" in t_lower or "insurance compan" in t_lower:
        return "INSURER"

    # 2. Precise doc_id token matching (avoiding bare '_comm_' and excluding '_pension_')
    if "_io_comm_" in d_lower or "_commercial_" in d_lower or "_internal_ombudsman_comm_" in d_lower:
        return "COMMERCIAL_BANK"
    if "_sfb_" in d_lower:
        return "SMALL_FINANCE_BANK"
    if "_nbfc_" in d_lower:
        return "NBFC"
    if "_ppi_" in d_lower:
        return "PPI_ISSUER"
    if "_cic_" in d_lower:
        return "CREDIT_INFORMATION_COMPANY"
    if "_agency_banks_" in d_lower or "_agency_" in d_lower:
        return "AGENCY_BANK"
    if "_primary_dealers_" in d_lower:
        return "PRIMARY_DEALER"

    return None


DOC_ALIASES: dict[str, str] = {
    "rbi_disbursement_pension_2026": "rbi_pension_2026",
    "rbi_internal_ombudsman_comm_2026": "rbi_io_comm_2026",
    "rbi_agency_banks_comm_2026": "rbi_agency_comm_2026",
    "sebi_currency_deriv_limits_2026": "sebi_currency_limits_2026",
}


def _ensure_manifest_metadata(manifest_meta: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """
    Loads manifest metadata and registers canonical aliases consistently,
    regardless of whether metadata is loaded from disk or provided by the caller.
    """
    meta_dict: dict[str, dict[str, Any]] = {}
    if manifest_meta is not None:
        meta_dict = {k: dict(v) for k, v in manifest_meta.items()}
    else:
        manifest_file = config.MANIFEST_FILE
        if manifest_file.is_file():
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    for r in csv.DictReader(f):
                        meta_dict[r["doc_id"]] = dict(r)
            except Exception as e:
                logger.error("Failed to load manifest file from %s: %s", manifest_file, e)
                raise
        else:
            logger.warning("Manifest file %s not found on disk.", manifest_file)

    # Consistently register aliases for all present documents (both directions)
    for orig, alias in DOC_ALIASES.items():
        if orig in meta_dict and alias not in meta_dict:
            meta_dict[alias] = dict(meta_dict[orig])
        elif alias in meta_dict and orig not in meta_dict:
            meta_dict[orig] = dict(meta_dict[alias])

    return meta_dict


def get_entity_matching_doc_ids(
    entity_type: str,
    manifest_meta: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """
    Returns all document IDs in the corpus matching the specified entity class.
    Consistently resolves aliases via _ensure_manifest_metadata.
    """
    meta_dict = _ensure_manifest_metadata(manifest_meta)

    matching_docs: set[str] = set()
    for did, r in meta_dict.items():
        title = r.get("title", "") if isinstance(r, dict) else ""
        if get_document_entity_type(did, title) == entity_type:
            matching_docs.add(did)
    return sorted(matching_docs)


COMMON_REGULATORY_TERMS: set[str] = {
    "reserve", "bank", "india", "directions", "guidelines", "master", "circular",
    "regulations", "framework", "scheme", "act", "provisions", "management", "risk",
    "notification", "rules", "instructions", "order", "board", "securities", "exchange",
    "insurance", "regulatory", "authority", "department", "financial", "services",
}

ENTITY_CLASS_TERMS: set[str] = {
    "commercial", "small", "finance", "banking", "company", "companies",
    "prepaid", "payment", "instrument", "instruments", "credit", "information",
    "agency", "primary", "dealer", "dealers", "mutual", "fund", "funds",
    "trust", "trusts", "estate", "infrastructure", "insurer", "insurers",
    "banks", "dealers",
}


def _extract_framework_topic_terms(text: str) -> set[str]:
    """Extracts distinctive subject-matter terms characterizing a statutory framework."""
    words = re.findall(r"[a-z]{4,}", text.lower())
    return {w for w in words if w not in COMMON_REGULATORY_TERMS and w not in ENTITY_CLASS_TERMS}


def is_competing_sibling_document(
    candidate_title: str,
    target_entity: str,
    query: str | None = None,
    manifest_meta: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """
    Determines whether a candidate document belongs to a competing statutory framework
    sibling (sharing the same subject matter/scheme as the query or target entity documents).
    Returns False for unrelated cross-regulatory or general documents.
    """
    cand_terms = _extract_framework_topic_terms(candidate_title)
    if not cand_terms:
        return False

    # When query is provided, check directly against the query's topic terms
    if query:
        q_terms = _extract_framework_topic_terms(query)
        return bool(cand_terms & q_terms)

    # Fallback when query is not provided (e.g. programmatic hits adjustment):
    # Check against target entity document titles in manifest
    if manifest_meta:
        for did, r in manifest_meta.items():
            t = r.get("title", "") if isinstance(r, dict) else ""
            if get_document_entity_type(did, t) == target_entity:
                target_terms = _extract_framework_topic_terms(t)
                if cand_terms & target_terms:
                    return True

    return False


def apply_entity_disambiguation_adjustment(
    hits: list[dict[str, Any]],
    entity_result: EntityDetectionResult,
    manifest_meta: dict[str, dict[str, Any]] | None = None,
    congruence_boost: float = 0.12,
    mismatch_penalty: float = 0.10,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """
    Applies calibrated entity-congruence adjustments to candidate scores.

    Rules:
    - If confidence is not 'explicit' or entity_type is None, returns hits unchanged.
    - If candidate document entity matches the explicit query entity, awards congruence_boost (+0.12).
    - If candidate document entity belongs to a competing sibling circular on the same framework,
      applies mismatch_penalty (-0.10).
    - Unrelated cross-regulatory or unclassified documents receive 0.0 adjustment (not penalized).
    - Preserves all candidate attributes, citations, and provenance metadata.
    - Sorts candidates descending by adjusted score.
    """
    if entity_result.confidence != "explicit" or not entity_result.entity_type:
        return hits

    meta_dict = _ensure_manifest_metadata(manifest_meta)
    target_entity = entity_result.entity_type
    adjusted: list[dict[str, Any]] = []

    for h in hits:
        h_copy = dict(h)
        did = h.get("document_id", "")
        doc_entry = meta_dict.get(did, {})
        title = doc_entry.get("title", "") if isinstance(doc_entry, dict) else ""
        doc_entity = get_document_entity_type(did, title)

        entity_adj = 0.0
        if doc_entity is not None:
            if doc_entity == target_entity:
                entity_adj = congruence_boost
            elif is_competing_sibling_document(title, target_entity, query=query, manifest_meta=meta_dict):
                entity_adj = -mismatch_penalty

        h_copy["entity_adj"] = entity_adj
        h_copy["doc_entity"] = doc_entity
        h_copy["score"] = h_copy.get("score", 0.0) + entity_adj
        adjusted.append(h_copy)

    adjusted.sort(key=lambda x: x["score"], reverse=True)
    return adjusted
