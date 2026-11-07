"""
PolicyLens (Case Study 2) – Lifecycle Registry, Version Control & Guarded Storage

Implements Phase 3.2.1 architecture:
- SQLite version lifecycle tracking with CAS promotion and transition triggers.
- Safe schema migration supporting the 'revoked' state and foreign-key integrity.
- Pre-ingestion exact vector metadata validation.
- Active-fingerprint-isolated retrieval and idempotent late-write reconciliation.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


# =============================================================================
# Custom Exception Hierarchy
# =============================================================================

class LifecycleRegistryError(Exception):
    """Base exception for all lifecycle and registry operations."""
    pass


class FencingRevokedError(LifecycleRegistryError):
    """Raised when a worker's fencing token or lease is revoked or invalid."""
    pass


class StalePromotionError(LifecycleRegistryError):
    """Raised when a candidate promotion is rejected due to concurrent CAS mismatch."""
    pass


class PromotionError(LifecycleRegistryError):
    """Raised when promotion preconditions or invariants are violated."""
    pass


class VectorMetadataMismatchError(LifecycleRegistryError):
    """Raised when chunk metadata violates exact expected ingestion context."""
    pass


# =============================================================================
# Database Connection Helper
# =============================================================================

def get_database_connection(db_path: str | Path, timeout: float = 30.0) -> sqlite3.Connection:
    """
    Opens a SQLite database connection with strict foreign-key enforcement,
    WAL journal mode, normal synchronous mode, and busy timeout.
    """
    conn = sqlite3.connect(str(db_path), timeout=timeout, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    return conn


# =============================================================================
# Schema Initialization
# =============================================================================

def init_lifecycle_schema(conn: sqlite3.Connection) -> None:
    """
    Initializes the PolicyLens lifecycle and document registry tables, indexes,
    and state-transition enforcement triggers.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS version_lifecycle (
            document_id TEXT NOT NULL,
            collection_name TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            version_id TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('staging', 'revoked', 'verified', 'active', 'superseded', 'failed')),
            host_id TEXT NOT NULL,
            worker_id TEXT NOT NULL,
            pid INTEGER NOT NULL,
            process_start_time REAL NOT NULL,
            fencing_token INTEGER NOT NULL DEFAULT 1,
            expected_active_fingerprint TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            lease_expires_at TEXT NOT NULL,
            chunk_count INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            validation_report_json TEXT,
            error_message TEXT,
            PRIMARY KEY (document_id, collection_name, fingerprint)
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS document_registry (
            document_id TEXT NOT NULL,
            collection_name TEXT NOT NULL,
            active_fingerprint TEXT NOT NULL,
            active_version_id TEXT NOT NULL,
            chunk_count INTEGER NOT NULL,
            total_tokens INTEGER NOT NULL,
            promoted_at TEXT NOT NULL,
            promoted_by TEXT NOT NULL,
            PRIMARY KEY (document_id, collection_name),
            FOREIGN KEY (document_id, collection_name, active_fingerprint) 
                REFERENCES version_lifecycle(document_id, collection_name, fingerprint)
        );
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_active_version 
        ON version_lifecycle(document_id, collection_name) 
        WHERE state = 'active';
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_staging_version 
        ON version_lifecycle(document_id, collection_name) 
        WHERE state = 'staging';
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_enforce_lifecycle_transition
        BEFORE UPDATE OF state ON version_lifecycle
        FOR EACH ROW
        WHEN OLD.state != NEW.state
        BEGIN
            SELECT CASE
                WHEN OLD.state = 'staging'  AND NEW.state IN ('verified', 'revoked', 'failed') THEN 1
                WHEN OLD.state = 'revoked'  AND NEW.state = 'failed' THEN 1
                WHEN OLD.state = 'verified' AND NEW.state IN ('active', 'failed') THEN 1
                WHEN OLD.state = 'active'   AND NEW.state = 'superseded' THEN 1
                ELSE RAISE(ABORT, 'Illegal lifecycle state transition')
            END;
        END;
        """
    )


# =============================================================================
# Safe SQLite Schema Migration
# =============================================================================

def migrate_lifecycle_schema(db_path: str | Path) -> None:
    """
    Safely updates version_lifecycle schema to include 'revoked' state and
    'expected_active_fingerprint'.
    Preserves all existing records, foreign-key relationships, and indexes.
    Recreates trg_enforce_lifecycle_transition inside the migration transaction.
    Executes foreign_key_check before committing.
    """
    conn = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
    
    # Step 1: Foreign keys MUST be disabled outside a transaction for table re-creation
    conn.execute("PRAGMA foreign_keys = OFF;")
    
    try:
        # Step 2: Begin exclusive migration transaction
        conn.execute("BEGIN IMMEDIATE;")
        
        # Check if version_lifecycle table exists
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='version_lifecycle'"
        ).fetchone()
        
        if not table_exists:
            init_lifecycle_schema(conn)
            conn.execute("COMMIT;")
            return
            
        cols = [r[1] for r in conn.execute("PRAGMA table_info(version_lifecycle)").fetchall()]
        has_expected_fp = "expected_active_fingerprint" in cols
        
        # Step 3: Create replacement table with 'revoked' in CHECK constraint
        conn.execute(
            """
            CREATE TABLE version_lifecycle_new (
                document_id TEXT NOT NULL,
                collection_name TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                version_id TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('staging', 'revoked', 'verified', 'active', 'superseded', 'failed')),
                host_id TEXT NOT NULL,
                worker_id TEXT NOT NULL,
                pid INTEGER NOT NULL,
                process_start_time REAL NOT NULL,
                fencing_token INTEGER NOT NULL DEFAULT 1,
                expected_active_fingerprint TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                lease_expires_at TEXT NOT NULL,
                chunk_count INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                validation_report_json TEXT,
                error_message TEXT,
                PRIMARY KEY (document_id, collection_name, fingerprint)
            );
            """
        )
        
        # Step 4: Transfer all existing records
        expected_fp_col = "expected_active_fingerprint" if has_expected_fp else "NULL AS expected_active_fingerprint"
        conn.execute(
            f"""
            INSERT INTO version_lifecycle_new 
            SELECT document_id, collection_name, fingerprint, version_id, state,
                   host_id, worker_id, pid, process_start_time, fencing_token,
                   {expected_fp_col},
                   created_at, updated_at, lease_expires_at, chunk_count, total_tokens,
                   validation_report_json, error_message 
            FROM version_lifecycle;
            """
        )
        
        # Step 5 & 6: Drop old table and rename replacement
        conn.execute("DROP TABLE version_lifecycle;")
        conn.execute("ALTER TABLE version_lifecycle_new RENAME TO version_lifecycle;")
        
        # Step 7: Recreate partial indexes
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_active_version 
            ON version_lifecycle(document_id, collection_name) 
            WHERE state = 'active';
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_staging_version 
            ON version_lifecycle(document_id, collection_name) 
            WHERE state = 'staging';
            """
        )
        
        # Step 8: Recreate the state transition enforcement trigger
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_enforce_lifecycle_transition
            BEFORE UPDATE OF state ON version_lifecycle
            FOR EACH ROW
            WHEN OLD.state != NEW.state
            BEGIN
                SELECT CASE
                    WHEN OLD.state = 'staging'  AND NEW.state IN ('verified', 'revoked', 'failed') THEN 1
                    WHEN OLD.state = 'revoked'  AND NEW.state = 'failed' THEN 1
                    WHEN OLD.state = 'verified' AND NEW.state IN ('active', 'failed') THEN 1
                    WHEN OLD.state = 'active'   AND NEW.state = 'superseded' THEN 1
                    ELSE RAISE(ABORT, 'Illegal lifecycle state transition')
                END;
            END;
            """
        )
        
        # Step 9: Validate foreign-key integrity before committing
        fk_violations = conn.execute("PRAGMA foreign_key_check;").fetchall()
        if fk_violations:
            raise sqlite3.IntegrityError(f"Foreign key integrity check failed after migration: {fk_violations}")
            
        # Step 10: Commit migration transaction
        conn.execute("COMMIT;")
        
    except Exception as e:
        conn.execute("ROLLBACK;")
        raise RuntimeError(f"Migration aborted and rolled back: {e}") from e
    finally:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.close()


# =============================================================================
# Lifecycle Worker Protocol Operations
# =============================================================================

def register_staging_candidate(
    conn: sqlite3.Connection,
    document_id: str,
    collection_name: str,
    fingerprint: str,
    version_id: str,
    host_id: str,
    worker_id: str,
    pid: int,
    process_start_time: float,
    lease_duration_seconds: int = 600,
    fencing_token: int = 1
) -> str | None:
    """
    Registers a new version in 'staging' state.
    Captures and persists expected_active_fingerprint at the instant of creation.
    Returns the persisted expected_active_fingerprint (or None if no prior active version).
    """
    now = datetime.now(timezone.utc).isoformat()
    lease_expires = datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() + lease_duration_seconds, tz=timezone.utc
    ).isoformat()
    
    cursor = conn.cursor()
    cursor.execute(
        "SELECT active_fingerprint FROM document_registry WHERE document_id = ? AND collection_name = ?",
        (document_id, collection_name)
    )
    row = cursor.fetchone()
    expected_active_fp = row[0] if row else None
    
    cursor.execute(
        """
        INSERT INTO version_lifecycle (
            document_id, collection_name, fingerprint, version_id, state,
            host_id, worker_id, pid, process_start_time, fencing_token,
            expected_active_fingerprint, created_at, updated_at, lease_expires_at
        ) VALUES (?, ?, ?, ?, 'staging', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_id, collection_name, fingerprint, version_id,
            host_id, worker_id, pid, process_start_time, fencing_token,
            expected_active_fp, now, now, lease_expires
        )
    )
    return expected_active_fp


def verify_staging_candidate(
    conn: sqlite3.Connection,
    document_id: str,
    collection_name: str,
    fingerprint: str,
    worker_id: str,
    fencing_token: int,
    chunk_count: int,
    total_tokens: int,
    validation_report_json: str = "{}"
) -> None:
    """
    Transitions staging -> verified only if the worker owns the current fencing token and lease.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE version_lifecycle
        SET state = 'verified',
            chunk_count = ?,
            total_tokens = ?,
            validation_report_json = ?,
            updated_at = datetime('now')
        WHERE document_id = ? 
          AND collection_name = ? 
          AND fingerprint = ? 
          AND worker_id = ? 
          AND fencing_token = ? 
          AND state = 'staging';
        """,
        (
            chunk_count, total_tokens, validation_report_json,
            document_id, collection_name, fingerprint, worker_id, fencing_token
        )
    )
    if cursor.rowcount != 1:
        raise FencingRevokedError(
            f"Failed to verify staging candidate: worker '{worker_id}' with token {fencing_token} "
            f"revoked or state is not 'staging'."
        )


def check_worker_lease_and_fence(
    conn: sqlite3.Connection,
    document_id: str,
    collection_name: str,
    fingerprint: str,
    worker_id: str,
    fencing_token: int,
    extend_seconds: int = 600
) -> bool:
    """
    Validates that the worker still owns the staging lease and fencing token.
    Extends the lease if valid. Returns True if ownership is intact, False otherwise.
    """
    cursor = conn.cursor()
    new_expires = datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() + extend_seconds, tz=timezone.utc
    ).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    
    cursor.execute(
        """
        UPDATE version_lifecycle
        SET lease_expires_at = ?,
            updated_at = ?
        WHERE document_id = ? 
          AND collection_name = ? 
          AND fingerprint = ? 
          AND worker_id = ? 
          AND fencing_token = ? 
          AND state = 'staging';
        """,
        (new_expires, now, document_id, collection_name, fingerprint, worker_id, fencing_token)
    )
    return cursor.rowcount == 1


def reap_stalled_staging(
    conn: sqlite3.Connection,
    document_id: str,
    collection_name: str,
    fingerprint: str
) -> bool:
    """
    Reaper action: Revokes an expired staging lease.
    Increments fencing_token and transitions state from 'staging' to 'revoked'.
    """
    cursor = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        """
        UPDATE version_lifecycle
        SET state = 'revoked',
            fencing_token = fencing_token + 1,
            updated_at = ?
        WHERE document_id = ? 
          AND collection_name = ? 
          AND fingerprint = ? 
          AND state = 'staging'
          AND lease_expires_at < ?;
        """,
        (now, document_id, collection_name, fingerprint, now)
    )
    return cursor.rowcount == 1


def fail_revoked_version(
    conn: sqlite3.Connection,
    document_id: str,
    collection_name: str,
    fingerprint: str,
    error_message: str = "Lease expired and reaped"
) -> bool:
    """
    Reaper action: Transitions 'revoked' -> 'failed' after quarantine/drain.
    """
    cursor = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        """
        UPDATE version_lifecycle
        SET state = 'failed',
            error_message = ?,
            updated_at = ?
        WHERE document_id = ? 
          AND collection_name = ? 
          AND fingerprint = ? 
          AND state = 'revoked';
        """,
        (error_message, now, document_id, collection_name, fingerprint)
    )
    return cursor.rowcount == 1


# =============================================================================
# CAS-Based Candidate Promotion
# =============================================================================

def promote_verified_candidate(
    conn: sqlite3.Connection,
    document_id: str,
    collection_name: str,
    candidate_fingerprint: str,
    worker_id: str,
    fencing_token: int,
    chunk_count: int | None = None,
    total_tokens: int | None = None
) -> dict[str, Any]:
    """
    Promotes a verified candidate version to 'active' using Compare-And-Swap.
    Compares the PERSISTED expected_active_fingerprint (from version_lifecycle)
    against the current active_fingerprint in document_registry.
    Does NOT derive or overwrite expected_active_fingerprint at promotion time.
    """
    cursor = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    
    conn.execute("BEGIN IMMEDIATE;")
    try:
        # 1. Fetch candidate version record, including persisted expected_active_fingerprint
        cursor.execute(
            """
            SELECT expected_active_fingerprint, version_id, chunk_count, total_tokens, state
            FROM version_lifecycle
            WHERE document_id = ? AND collection_name = ? AND fingerprint = ? 
              AND worker_id = ? AND fencing_token = ?
            """,
            (document_id, collection_name, candidate_fingerprint, worker_id, fencing_token)
        )
        candidate = cursor.fetchone()
        if not candidate:
            raise FencingRevokedError(
                f"Candidate not found or worker_id/fencing_token revoked for fingerprint {candidate_fingerprint}."
            )
            
        persisted_expected_fp, version_id, stored_chunk_count, stored_total_tokens, state = candidate
        
        if state != "verified":
            raise PromotionError(
                f"Candidate promotion rejected: state is '{state}', expected 'verified'."
            )
            
        final_chunk_count = chunk_count if chunk_count is not None else stored_chunk_count
        final_total_tokens = total_tokens if total_tokens is not None else stored_total_tokens

        # 2. Check current active version in document_registry
        cursor.execute(
            "SELECT active_fingerprint FROM document_registry WHERE document_id = ? AND collection_name = ?",
            (document_id, collection_name)
        )
        current_active_row = cursor.fetchone()
        current_active_fp = current_active_row[0] if current_active_row else None
        
        # CAS Verification against persisted expected_active_fingerprint
        if current_active_fp != persisted_expected_fp:
            raise StalePromotionError(
                f"Stale candidate rejected: current active fingerprint '{current_active_fp}' "
                f"does not match persisted expected fingerprint '{persisted_expected_fp}'."
            )
            
        # 3. Demote currently active version (if present)
        if current_active_fp is not None:
            cursor.execute(
                """
                UPDATE version_lifecycle
                SET state = 'superseded', updated_at = ?
                WHERE document_id = ? AND collection_name = ? 
                  AND fingerprint = ? AND state = 'active';
                """,
                (now, document_id, collection_name, current_active_fp)
            )
            if cursor.rowcount != 1:
                raise StalePromotionError(
                    "Demotion failed: active version was concurrently modified or removed."
                )

        # 4. Promote candidate from verified -> active
        cursor.execute(
            """
            UPDATE version_lifecycle
            SET state = 'active', updated_at = ?
            WHERE document_id = ? AND collection_name = ? 
              AND fingerprint = ? AND worker_id = ? 
              AND fencing_token = ? AND state = 'verified';
            """,
            (now, document_id, collection_name, candidate_fingerprint, worker_id, fencing_token)
        )
        if cursor.rowcount != 1:
            raise PromotionError(
                "Candidate promotion query failed: state was modified or worker revoked."
            )

        # 5. Atomically update document_registry
        cursor.execute(
            """
            INSERT INTO document_registry (
                document_id, collection_name, active_fingerprint, active_version_id,
                chunk_count, total_tokens, promoted_at, promoted_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_id, collection_name) DO UPDATE SET
                active_fingerprint = excluded.active_fingerprint,
                active_version_id = excluded.active_version_id,
                chunk_count = excluded.chunk_count,
                total_tokens = excluded.total_tokens,
                promoted_at = excluded.promoted_at,
                promoted_by = excluded.promoted_by;
            """,
            (
                document_id, collection_name, candidate_fingerprint, version_id,
                final_chunk_count, final_total_tokens, now, worker_id
            )
        )
        
        conn.execute("COMMIT;")
        return {
            "status": "promoted",
            "document_id": document_id,
            "collection_name": collection_name,
            "active_fingerprint": candidate_fingerprint,
            "version_id": version_id,
            "chunk_count": final_chunk_count,
            "total_tokens": final_total_tokens,
            "promoted_at": now
        }
    except Exception:
        conn.execute("ROLLBACK;")
        raise


# =============================================================================
# Strict Vector Metadata Validation
# =============================================================================

def validate_vector_batch_metadata(
    metadatas: Sequence[dict[str, Any]],
    expected_doc_id: str,
    expected_collection: str,
    expected_fingerprint: str,
    expected_version_id: str
) -> None:
    """
    Validates batch metadata against expected ingestion context.
    Rejects empty expected-context values before validating the batch.
    Rejects missing, empty, or mismatched metadata in any item.
    """
    # 1. Reject empty expected-context values before validating the batch
    if not expected_doc_id or not isinstance(expected_doc_id, str) or not expected_doc_id.strip():
        raise VectorMetadataMismatchError("Expected document_id cannot be empty or non-string.")
    if not expected_collection or not isinstance(expected_collection, str) or not expected_collection.strip():
        raise VectorMetadataMismatchError("Expected collection_name cannot be empty or non-string.")
    if not expected_fingerprint or not isinstance(expected_fingerprint, str) or not expected_fingerprint.strip():
        raise VectorMetadataMismatchError("Expected index_fingerprint cannot be empty or non-string.")
    if not expected_version_id or not isinstance(expected_version_id, str) or not expected_version_id.strip():
        raise VectorMetadataMismatchError("Expected version_id cannot be empty or non-string.")
        
    expected_doc_id = expected_doc_id.strip()
    expected_collection = expected_collection.strip()
    expected_fingerprint = expected_fingerprint.strip()
    expected_version_id = expected_version_id.strip()

    if not metadatas:
        raise VectorMetadataMismatchError("Metadata batch cannot be empty.")

    # 2. Validate every vector's metadata
    for idx, meta in enumerate(metadatas):
        if not isinstance(meta, dict):
            raise VectorMetadataMismatchError(f"Vector metadata at index {idx} must be a dictionary.")
            
        doc_id = meta.get("document_id")
        if not doc_id or not isinstance(doc_id, str) or doc_id.strip() != expected_doc_id:
            raise VectorMetadataMismatchError(
                f"Metadata mismatch at chunk {idx}: document_id '{doc_id}' != expected '{expected_doc_id}'."
            )

        coll = meta.get("collection_name")
        if not coll or not isinstance(coll, str) or coll.strip() != expected_collection:
            raise VectorMetadataMismatchError(
                f"Metadata mismatch at chunk {idx}: collection_name '{coll}' != expected '{expected_collection}'."
            )

        fp = meta.get("index_fingerprint")
        if not fp or not isinstance(fp, str) or fp.strip() != expected_fingerprint:
            raise VectorMetadataMismatchError(
                f"Metadata mismatch at chunk {idx}: index_fingerprint '{fp}' != expected '{expected_fingerprint}'."
            )

        ver_id = meta.get("version_id")
        if not ver_id or not isinstance(ver_id, str) or ver_id.strip() != expected_version_id:
            raise VectorMetadataMismatchError(
                f"Metadata mismatch at chunk {idx}: version_id '{ver_id}' != expected '{expected_version_id}'."
            )


def write_chunk_batch_guarded(
    chroma_collection: Any,
    ids: Sequence[str],
    embeddings: Sequence[Sequence[float]],
    documents: Sequence[str],
    metadatas: Sequence[dict[str, Any]],
    expected_doc_id: str,
    expected_collection: str,
    expected_fingerprint: str,
    expected_version_id: str
) -> None:
    """
    Validates batch metadata before any ChromaDB write.
    Guarantees that ChromaDB.add() is NEVER called if any validation fails.
    """
    if not (len(ids) == len(embeddings) == len(documents) == len(metadatas)):
        raise VectorMetadataMismatchError(
            f"Batch dimension mismatch: ids={len(ids)}, embeddings={len(embeddings)}, "
            f"documents={len(documents)}, metadatas={len(metadatas)}."
        )

    # Validate metadata before ChromaDB write
    validate_vector_batch_metadata(
        metadatas=metadatas,
        expected_doc_id=expected_doc_id,
        expected_collection=expected_collection,
        expected_fingerprint=expected_fingerprint,
        expected_version_id=expected_version_id
    )

    # Validated: call ChromaDB
    chroma_collection.add(
        ids=list(ids),
        embeddings=list(embeddings),
        documents=list(documents),
        metadatas=list(metadatas)
    )


# =============================================================================
# Active Retrieval Isolation & Idempotent Reconciliation Sweeper
# =============================================================================

def retrieve_active_corpus(
    db_conn: sqlite3.Connection,
    chroma_collection: Any,
    collection_name: str,
    query_embeddings: Sequence[Sequence[float]],
    top_k: int = 5,
    where_additional: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    Executes isolated vector retrieval strictly across active fingerprints.
    Guarantees:
    - If there are no active fingerprints, returns an empty result dictionary without querying ChromaDB.
    - No unverified, staging, revoked, superseded, or failed versions can leak into retrieval.
    - No retrieval fallback may bypass the active-fingerprint filter.
    """
    if not collection_name or not isinstance(collection_name, str):
        raise ValueError("collection_name must be a non-empty string.")

    # 1. Atomic read snapshot of active fingerprints from document_registry
    cursor = db_conn.cursor()
    cursor.execute("BEGIN DEFERRED;")
    try:
        cursor.execute(
            "SELECT active_fingerprint FROM document_registry WHERE collection_name = ?",
            (collection_name,)
        )
        active_fps = [row[0] for row in cursor.fetchall() if row[0]]
        cursor.execute("COMMIT;")
    except Exception:
        cursor.execute("ROLLBACK;")
        raise

    # Invariant: Empty active set returns empty result immediately without touching ChromaDB
    if not active_fps:
        return {
            "ids": [[] for _ in query_embeddings],
            "documents": [[] for _ in query_embeddings],
            "metadatas": [[] for _ in query_embeddings],
            "distances": [[] for _ in query_embeddings]
        }

    # 2. Build strict active filter
    if len(active_fps) == 1:
        base_filter = {"$and": [{"collection_name": collection_name}, {"index_fingerprint": active_fps[0]}]}
    else:
        base_filter = {"$and": [{"collection_name": collection_name}, {"index_fingerprint": {"$in": active_fps}}]}

    if where_additional:
        final_filter = {"$and": [base_filter, where_additional]}
    else:
        final_filter = base_filter

    # 3. Query ChromaDB with mandatory filter
    return chroma_collection.query(
        query_embeddings=list(query_embeddings),
        n_results=top_k,
        where=final_filter
    )


def run_reconciliation_sweeper(
    db_conn: sqlite3.Connection,
    chroma_collection: Any,
    collection_name: str | None = None
) -> int:
    """
    Idempotent reconciliation sweeper:
    Queries SQLite for all versions in 'failed', 'revoked', or expired 'superseded' state (> 30 days)
    and purges any orphaned vectors from ChromaDB matching their version_id.
    Returns the count of purged version IDs.
    """
    cursor = db_conn.cursor()
    query = """
        SELECT DISTINCT version_id 
        FROM version_lifecycle 
        WHERE (
            state IN ('revoked', 'failed')
            OR (state = 'superseded' AND datetime(updated_at) < datetime('now', '-30 days'))
        )
    """
    params = []
    if collection_name:
        query += " AND collection_name = ?"
        params.append(collection_name)
        
    cursor.execute(query, tuple(params))
    dead_version_ids = [row[0] for row in cursor.fetchall()]
    
    purged_count = 0
    for v_id in dead_version_ids:
        # ChromaDB delete is idempotent
        chroma_collection.delete(where={"version_id": v_id})
        purged_count += 1
        
    return purged_count

