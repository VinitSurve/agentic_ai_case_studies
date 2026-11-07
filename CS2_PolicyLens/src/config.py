"""
PolicyLens – Central Configuration Module

Defines system paths, parsing parameters, OCR thresholds, chunking boundaries,
and vector database settings for Case Study 2.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PolicyLensConfig:
    # 1. Directory & File Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    DATA_DIR: Path = BASE_DIR / "data"
    PDF_DIR: Path = DATA_DIR / "pdfs"
    MANIFEST_FILE: Path = DATA_DIR / "manifest.csv"
    CHECKPOINT_FILE: Path = DATA_DIR / ".ingestion_checkpoint.json"
    CHROMA_DIR: Path = DATA_DIR / "chroma_db"
    REGISTRY_DB_PATH: Path = DATA_DIR / "policylens_registry.db"

    EVAL_DIR: Path = BASE_DIR / "eval"
    QUESTIONS_FILE: Path = EVAL_DIR / "questions.csv"
    METRICS_FILE: Path = EVAL_DIR / "metrics.csv"
    RETRIEVAL_LOG_FILE: Path = EVAL_DIR / "retrieval_log.csv"
    TABLE_AUDIT_FILE: Path = EVAL_DIR / "table_audit.csv"

    LOGS_DIR: Path = BASE_DIR / "logs"
    RUN1_LOG: Path = LOGS_DIR / "run1.log"
    RUN2_LOG: Path = LOGS_DIR / "run2_rerun.log"
    FAILURES_LOG: Path = LOGS_DIR / "ingestion_failures.jsonl"
    OCR_LOG: Path = LOGS_DIR / "ocr_diagnostics.jsonl"

    EVIDENCE_DIR: Path = BASE_DIR / "evidence"
    DEMO_DIR: Path = BASE_DIR / "demo"
    REPORT_DIR: Path = BASE_DIR / "report"

    # 2. OCR Configuration
    TESSERACT_CMD: str = (
        "/opt/homebrew/bin/tesseract"
        if Path("/opt/homebrew/bin/tesseract").is_file()
        else (shutil.which("tesseract") or "tesseract")
    )
    OCR_DPI: int = 300
    OCR_MIN_TEXT_CHARS: int = 50
    OCR_IMAGE_COVERAGE_RATIO: float = 0.50
    OCR_QUALITY_RATIO_MIN: float = 0.60

    # 3. Layout Analysis
    FULL_WIDTH_RATIO: float = 0.65
    COLUMN_LEFT_MAX_X: float = 0.55
    COLUMN_RIGHT_MIN_X: float = 0.45

    # 4. Chunk Sizing (in Tokens)
    TOKENIZER_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    FIXED_CHUNK_SIZE: int = 500
    FIXED_CHUNK_OVERLAP: int = 50
    MIN_CHUNK_SIZE: int = 300
    MAX_CHUNK_SIZE: int = 800

    # 5. Table Extractions
    TABLE_MAX_EMPTY_CELL_RATIO: float = 0.40

    # 6. Embedding & Vector Database
    EMBEDDING_MODEL_NAME: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIM: int = 384
    EMBEDDING_BATCH_SIZE: int = 64
    SIMILARITY_METRIC: str = "cosine"
    COLLECTION_FIXED: str = "policylens_fixed"
    COLLECTION_STRUCTURE: str = "policylens_structure"

    # Safe hardware selection (CPU by default)
    @property
    def device(self) -> str:
        # Default to CPU-compatible execution for rock-solid stability
        return os.getenv("POLICYLENS_DEVICE", "cpu")


# Global singleton instance
config = PolicyLensConfig()

