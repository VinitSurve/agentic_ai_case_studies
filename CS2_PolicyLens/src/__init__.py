"""
PolicyLens (Case Study 2) – Core Package

Exports PDF parsing, layout analysis, OCR engine, table extraction,
and structured intermediate representation models.
"""

from CS2_PolicyLens.src.config import PolicyLensConfig, config
from CS2_PolicyLens.src.chunker import DocumentChunk, RegulatoryChunker
from CS2_PolicyLens.src.embeddings import EmbeddingEngine, MockEmbeddingEngine
from CS2_PolicyLens.src.indexing_pipeline import (
    compute_index_fingerprint,
    index_pdf_document,
    query_policy_corpus,
)
from CS2_PolicyLens.src.layout_analyzer import LayoutAnalyzer
from CS2_PolicyLens.src.models import (
    BlockType,
    BoundingBox,
    DocumentDiagnostics,
    ExtractionMethod,
    PageDiagnostics,
    ParsedBlock,
    ParsedDocument,
)
from CS2_PolicyLens.src.ocr_engine import OCREngine
from CS2_PolicyLens.src.pdf_parser import PDFParser
from CS2_PolicyLens.src.rag_qa import SYSTEM_PROMPT, RegulatoryQAEngine
from CS2_PolicyLens.src.table_extractor import TableExtractor
from CS2_PolicyLens.src.version_registry import (
    FencingRevokedError,
    LifecycleRegistryError,
    PromotionError,
    StalePromotionError,
    VectorMetadataMismatchError,
    check_worker_lease_and_fence,
    fail_revoked_version,
    get_database_connection,
    init_lifecycle_schema,
    migrate_lifecycle_schema,
    promote_verified_candidate,
    reap_stalled_staging,
    register_staging_candidate,
    retrieve_active_corpus,
    run_reconciliation_sweeper,
    validate_vector_batch_metadata,
    verify_staging_candidate,
    write_chunk_batch_guarded,
)

__all__ = [
    "config",
    "PolicyLensConfig",
    "BlockType",
    "BoundingBox",
    "ExtractionMethod",
    "ParsedBlock",
    "PageDiagnostics",
    "DocumentDiagnostics",
    "ParsedDocument",
    "OCREngine",
    "TableExtractor",
    "LayoutAnalyzer",
    "PDFParser",
    "LifecycleRegistryError",
    "FencingRevokedError",
    "StalePromotionError",
    "PromotionError",
    "VectorMetadataMismatchError",
    "get_database_connection",
    "init_lifecycle_schema",
    "migrate_lifecycle_schema",
    "register_staging_candidate",
    "verify_staging_candidate",
    "check_worker_lease_and_fence",
    "reap_stalled_staging",
    "fail_revoked_version",
    "promote_verified_candidate",
    "validate_vector_batch_metadata",
    "write_chunk_batch_guarded",
    "retrieve_active_corpus",
    "run_reconciliation_sweeper",
    "DocumentChunk",
    "RegulatoryChunker",
    "EmbeddingEngine",
    "MockEmbeddingEngine",
    "compute_index_fingerprint",
    "index_pdf_document",
    "query_policy_corpus",
    "RegulatoryQAEngine",
    "SYSTEM_PROMPT",
]
