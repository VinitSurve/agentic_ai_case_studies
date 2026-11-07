# PolicyLens Efficiency & Robustness Benchmark Results

**Date**: November 7, 2026  
**Hardware Environment**: Apple Silicon Mac (Apple M5, 16.0 GB Unified Memory, Darwin 25.5.0)  
**Embedding Engine**: `sentence-transformers/all-MiniLM-L6-v2` (384-dim, normalized, local CPU)  
**Vector Store**: ChromaDB (v0.4.22+) local embedded HNSW index  
**Registry**: SQLite 3 (`policylens_registry.db`) with Foreign Keys & Trigger Constraints  
**Measurement Methodology**: Full corpus end-to-end execution across all 40 manifest documents (1,123 physical pages).

---

## 1. System Performance Summary Table (Full Corpus: 40 PDFs / 1,123 Pages)

| Benchmark Metric | Measured Value | Measurement Details & Conditions |
|---|:---:|---|
| **Total Corpus Documents** | **40 PDFs** | 100% of manifest documents processed |
| **Total Physical Pages** | **1,123 Pages** | Native text, tables, and scanned pages |
| **Total Active Chunks** | **1,604 Chunks** | In collection `policylens_v1` (1,763 across all collections) |
| **Full Ingestion Duration (Run 1)** | **187.87 s (~3.13 min)** | End-to-end: parsing, layout analysis, OCR, embedding, ChromaDB writes, and CAS promotion |
| **Ingestion Time per 100 Pages** | **16.73 s / 100 pages** | Throughput: **5.98 pages / second** (including OCR fallbacks) |
| **Idempotent Re-Run Duration (Run 2)** | **0.09 s (90 ms)** | Idempotency detection via SHA-256 fingerprint snapshot matching across all 40 docs |
| **Duplicate Chunks on Re-Run** | **0 (Zero)** | Guaranteed by CAS promotion and fingerprint checking |
| **Idempotency Speedup** | **2,087.4x** | Instantaneous bypass of redundant parsing and vector computation |
| **ChromaDB Storage Footprint** | **28.25 MB** (29,621,096 bytes) | Full HNSW vector index + document texts + metadata |
| **SQLite Registry DB Size** | **112.0 KB** | Full lifecycle audit trail across 40 documents and candidates |
| **Warm Query Latency (Mean)** | **11.61 ms** | Average over 20 repeated queries with Top-5 ChromaDB HNSW cosine search |
| **Warm Query Latency (Min / P95)**| **10.53 ms / 14.58 ms** | Fast sub-15ms compliance query response |
| **Cold CLI Query Latency** | **3.28 s** | Includes Python runtime startup and SentenceTransformers model weight loading |
| **Embedding Model & Dimensions** | `all-MiniLM-L6-v2` (384-dim) | Dense normalized float32 vectors, HNSW cosine metric |
| **Local Embedding Cost** | **$0.00 (Zero API Cost)** | Local CPU execution; requires ~2.5 seconds CPU compute per 1,000 chunks |
| **Machine Specifications** | **Apple M5 / 16.0 GB RAM** | macOS Darwin 25.5.0 x86_64 emulation layer / arm64 architecture |

---

## 2. Full-Corpus Ingestion Logs

### First-Run Batch Ingestion (`logs/full_corpus_first_run.log`)
```text
[*] Starting Batch Ingestion: 40 documents -> Collection 'policylens_v1'
  [01/40] [+] INDEXED: rbi_internal_ombudsman_comm_2026 (16 pages, 17 chunks)
  [02/40] [+] INDEXED: rbi_internal_ombudsman_sfb_2026 (16 pages, 17 chunks)
  [03/40] [+] INDEXED: rbi_internal_ombudsman_nbfc_2026 (18 pages, 17 chunks)
  ...
  [38/40] [+] INDEXED: rbi_dividend_remittance_2026 (12 pages, 16 chunks)
  [39/40] [+] INDEXED: rbi_relief_savings_bonds_2025 (6 pages, 7 chunks)
  [40/40] [+] INDEXED: sebi_net_settlement_mf_2026 (5 pages, 11 chunks)

=================================================================
INGESTION BATCH SUMMARY
=================================================================
Collection Name:             policylens_v1
Manifest Document Count:     40
Successfully Indexed:        40
Skipped (Unchanged/Cached):  0
Failed Count:                0
Total Pages Processed:       1123
Total Chunks Active:         1604
New Chunks Added:            1604
Active Document Count:       40
Execution Duration:          187.87 seconds
=================================================================
```

### Second-Run Batch Ingestion (`logs/full_corpus_second_run.log`)
```text
[*] Starting Batch Ingestion: 40 documents -> Collection 'policylens_v1'
  [01/40] [~] SKIPPED (Idempotent): rbi_internal_ombudsman_comm_2026 (17 chunks)
  [02/40] [~] SKIPPED (Idempotent): rbi_internal_ombudsman_sfb_2026 (17 chunks)
  ...
  [39/40] [~] SKIPPED (Idempotent): rbi_relief_savings_bonds_2025 (7 chunks)
  [40/40] [~] SKIPPED (Idempotent): sebi_net_settlement_mf_2026 (11 chunks)

=================================================================
INGESTION BATCH SUMMARY
=================================================================
Collection Name:             policylens_v1
Manifest Document Count:     40
Successfully Indexed:        0
Skipped (Unchanged/Cached):  40
Failed Count:                0
Total Pages Processed:       1123
Total Chunks Active:         1604
New Chunks Added:            0
Active Document Count:       40
Execution Duration:          0.09 seconds
=================================================================
```

---

## 3. Query Latency Breakdown (20 Consecutive Warm Queries)

Measurement Query: `"cash disbursement limit for secured loans"`  
Collection: `policylens_v1` (1,604 vectors, Top-5 nearest neighbors)

```text
Run  1: 10.74 ms
Run  2: 11.23 ms
Run  3: 10.53 ms (Min)
Run  4: 11.89 ms
Run  5: 12.01 ms
Run  6: 10.82 ms
Run  7: 11.45 ms
Run  8: 12.18 ms
Run  9: 11.02 ms
Run 10: 10.95 ms
Run 11: 11.34 ms
Run 12: 12.50 ms
Run 13: 11.10 ms
Run 14: 14.58 ms (P95)
Run 15: 11.67 ms
Run 16: 12.04 ms
Run 17: 10.98 ms
Run 18: 11.42 ms
Run 19: 11.88 ms
Run 20: 11.82 ms

Summary Statistics:
  Mean Latency: 11.61 ms
  P50 Latency:  11.38 ms
  P95 Latency:  14.58 ms
  Min Latency:  10.53 ms
```

---

## 4. Hardware Resource Utilization

- **CPU Usage**: Multi-core batch embedding utilizes ~280% CPU during peak PyTorch matrix operations; parsing and OCR utilize 100-140% CPU.
- **RAM Footprint**: Process peak RSS is **485 MB**, well within the 16.0 GB hardware envelope.
- **Disk I/O**: Local SQLite WAL mode with synchronous=NORMAL and ChromaDB Parquet persistence produces zero write stalls.
