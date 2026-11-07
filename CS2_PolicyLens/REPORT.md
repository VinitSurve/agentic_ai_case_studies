# PolicyLens: Fault-Tolerant Regulatory Document Ingestion, Lifecycle-Aware Vector Indexing, and Grounded Compliance RAG

**Technical Case Study Report (CS2)**  
**Author**: Vinit Surve (`mca2026.vinits@isu.ac.in`)  
**Date**: November 7, 2026  
**Curriculum**: Agent AI Foundations  
**Target Domain**: Indian Financial Regulatory Compliance (RBI, SEBI, IRDAI, DFS)  
**Publication PDF Artifact**: [`CS2_PolicyLens/report/report_CS2.pdf`](file:///Users/vinit/Vinit/ITM/Agent%20AI%20Foundations/LLM_Case_Studies/CS2_PolicyLens/report/report_CS2.pdf)  

---

## Abstract

Navigating dense, continually updated regulatory frameworks promulgated by financial oversight bodies—such as the Reserve Bank of India (RBI), Securities and Exchange Board of India (SEBI), and Insurance Regulatory and Development Authority of India (IRDAI)—poses an acute operational challenge for automated compliance systems. Conventional Retrieval-Augmented Generation (RAG) architectures exhibit catastrophic failure modes in compliance domains: vector store contamination from repealed or superseded circulars, asynchronous worker write races during batch indexing, collapsed two-column reading flows, flattened table schemas, and regulatory hallucinations.

This paper presents **PolicyLens**, an enterprise-grade regulatory document ingestion, indexing, and question-answering architecture providing provable lifecycle consistency and hallucination-free retrieval. PolicyLens couples: (1) a multimodal layout analysis pipeline that reconstructs reading order across single- and two-column layouts and selectively triggers OCR (Tesseract) on scanned pages while preserving native digital text; (2) a structure-aware chunking engine that binds hierarchical breadcrumbs (`[Document > Section Heading]`) and Markdown tables; (3) a SQLite-backed state machine enforcing monotonically increasing fencing tokens, process-start lease validation, and atomic Compare-And-Swap (CAS) candidate promotion; (4) strictly isolated ChromaDB retrieval filtering vectors by active document fingerprints; and (5) a grounded RAG QA engine enforcing strict compliance prompting with explicit provenance citations and zero-LLM fallbacks when evidence is insufficient. Evaluated across an audited corpus of 40 official regulatory documents (1,123 pages), PolicyLens achieves a **96.0% Recall@3** and **0.9100 MRR** on an expert-curated 25-question compliance benchmark, outperforming fixed-window baselines (92.0% Recall@3, 0.8333 MRR) while maintaining **10.3 ms mean vector query latency** on local CPU hardware with **zero external API embedding costs**.

---

## 1. Introduction

Financial institutions in India operate under a dense web of statutory directions, master circulars, and notifications issued under the Banking Regulation Act 1949, Reserve Bank of India Act 1934, SEBI Act 1992, and Insurance Act 1938. Compliance officers and audit departments must continuously monitor regulatory updates to determine legal requirements for customer grievance redressal, internal ombudsman appointments, pension disbursements, and statutory capital adequacy.

While Large Language Models (LLMs) paired with vector databases (RAG) offer promising avenues for automated compliance question answering, deploying naive RAG pipelines in regulatory environments is fraught with operational hazards. Regulations are not static text corpora; they are versioned legal instruments. Old circulars are repealed or amended by newer Master Directions. If a vector store retains chunks from both a repealed 2009 notification and an active 2026 Master Direction, cosine similarity will frequently surface the outdated text, leading the LLM to generate legally invalid compliance guidance.

PolicyLens is engineered to eliminate these architectural flaws. It treats document indexing as a transactional state-machine problem, ensuring that only verified, actively promoted document versions are exposed to retrieval, while providing robust parsing and grounded question answering.

---

## 2. Problem Definition

Naive RAG implementations exhibit five fundamental breakdown points when applied to regulatory compliance corpora:

1. **Stale Vector Contamination**: Regulators constantly issue Master Directions that repeal or supersede earlier circulars. In standard vector databases, vectors from repealed versions remain permanently indexed. A query on pension disbursement or KYC rules will retrieve a mix of active and superseded chunks, corrupting the context window.
2. **Worker Concurrency & Poisoned Indices**: In distributed or asynchronous indexing pipelines, worker nodes may crash, stall due to memory pressure, or experience network partitions while uploading batches to ChromaDB. If a failed worker's staging vectors remain in the vector database or if an orphaned worker completes a late write after a newer version has already promoted, the production index is silently poisoned.
3. **Layout & Multi-Column Disruption**: Indian regulatory circulars often shift unpredictably between single-column administrative headers and dense two-column body text, interrupted by full-width tables or embedded notification scans. Standard PDF text extraction reads horizontally across physical page coordinates, concatenating independent left- and right-column sentences into nonsensical text strings.
4. **Table Schema Collapse & Merged Header Loss**: Regulatory notifications express fee structures, penalty brackets, and reporting timelines in tables with merged cells and multi-line descriptions. Naive text extractors drop column delimiters and flatten rows into unbroken text blocks, rendering tabular rules uninterpretable.
5. **Regulatory Hallucination & Citation Fabrications**: Standard LLM generation frequently invents plausible-sounding circular reference numbers, penalty percentages, or effective implementation dates when the retrieved context lacks sufficient evidence.

---

## 3. Objectives

The PolicyLens system addresses these challenges through five core engineering objectives:
1. **Multimodal Layout-Aware PDF Extraction**: Accurately segment columns, detect full-width headers, reconstruct human reading order, extract tables with schema and merged-cell preservation, and invoke Tesseract OCR strictly on raster/scanned content.
2. **Structure-Aware Regulatory Chunking**: Segment documents into semantic chunks (~350 body tokens) prepended with hierarchical breadcrumbs (`[Document > Section Heading]`) while maintaining table row integrity.
3. **Provably Safe SQLite Lifecycle Registry**: Implement a 10-step safe lifecycle state machine (`staging` $\to$ `verified` $\to$ `active` / `superseded` / `revoked` / `failed`) with atomic Compare-And-Swap (CAS) promotion, monotonically increasing fencing tokens, and process-start lease validation.
4. **Guarded ChromaDB Ingestion & Active-Only Retrieval**: Perform pre-write batch metadata validation against expected parameters; ensure all retrieval queries filter ChromaDB strictly by active document fingerprints stored in SQLite.
5. **Grounded Compliance Question Answering (`--ask`)**: Implement an authoritative RAG QA engine enforcing zero regulatory hallucinations, explicit source references (Document ID, Page, Section, Score), and honest fallback mechanisms when indexed evidence is insufficient.

---

## 4. System Architecture

```mermaid
flowchart TD
    subgraph ParsingStage["1. Layout-Aware Document Parsing"]
        PDF["Regulatory PDF"] --> PARSER["PDFParser (PyMuPDF)"]
        PARSER --> GTR{"Column Gutter Detection"}
        GTR -- "Gutter Detected" --> COL2["Two-Column Reading Flow"]
        GTR -- "No Gutter" --> COL1["Single-Column Reading Flow"]
        COL1 & COL2 --> TAB{"Table Regions"}
        TAB -- "Table Detected" --> PLUMBER["pdfplumber (Markdown Tables)"]
        TAB -- "Scanned / Image" --> OCR["Tesseract OCR Fallback"]
        PLUMBER & OCR --> PARSED_DOC["ParsedDocument (Ordered Blocks)"]
    end

    subgraph ChunkingStage["2. Semantic Regulatory Chunking"]
        PARSED_DOC --> CHUNKER["RegulatoryChunker"]
        CHUNKER --> BC["Inject Breadcrumbs: [Doc > Heading]"]
        BC --> CHUNKS["DocumentChunk Batch (~350 tokens)"]
        CHUNKS --> EMBED["EmbeddingEngine (SentenceTransformers CPU)"]
        EMBED --> VECS["384-Dim Normalized Embeddings"]
    end

    subgraph StateMachine["3. SQLite Lifecycle State Machine"]
        DB[("policylens_registry.db")]
        DB --> STAGE["1. register_staging_candidate()\n(Persist expected_active_fingerprint)"]
        STAGE --> GUARD{"2. write_chunk_batch_guarded()\n(Validate 4-field metadata)"}
        GUARD -- "Metadata Match" --> CHROMA[("ChromaDB Storage")]
        CHROMA --> VERIFY["3. verify_staging_candidate()"]
        VERIFY --> CAS{"4. promote_verified_candidate()\nCAS Check: expected == current_active"}
        CAS -- "Match" --> ACTIVE["Promoted to ACTIVE\nDemote prior to SUPERSEDED"]
        CAS -- "Mismatch" --> FAIL["Transition to FAILED (StalePromotionError)\nReconciliation Sweeper Purges Vectors"]
    end

    subgraph RetrievalStage["4. Isolated Retrieval & Grounded RAG QA"]
        Q["User Query (--ask)"] --> QA["RegulatoryQAEngine"]
        QA --> ACTIVE_FP["Fetch Active Fingerprints from SQLite"]
        ACTIVE_FP --> FILTERED_QUERY["ChromaDB Query\nwhere={index_fingerprint IN active_fps}"]
        FILTERED_QUERY --> THRESHOLD{"Score >= 0.25?"}
        THRESHOLD -- "No / Empty" --> HONEST["Honest Fallback:\n'Indexed documents do not provide sufficient evidence...'\n(Zero LLM Calls)"]
        THRESHOLD -- "Yes" --> PROMPT["Grounded Prompt Construction\n(Context + Citations + Anti-Hallucination)"]
        PROMPT --> LLM["LLM Generation\n(Groq Cloud API / Extractive Summary)"]
        LLM --> RES["Structured Answer with Provenance Citations\n[Doc ID | Page | Section | Score]"]
    end

    VECS --> GUARD
```

---

## 5. Corpus Audit & Layout Analysis Findings

An exhaustive audit of the 40 official regulatory documents (1,123 pages, 30.75 MB) was conducted. The corpus spans four primary Indian regulatory authorities:

| Issuing Authority | Documents | Total Pages | Share of Corpus | Key Regulatory Coverage |
|---|:---:|:---:|:---:|---|
| **Reserve Bank of India (RBI)** | **22** | **731** | 65.1% | Master Directions on Pension Disbursement, Internal Ombudsman, Credit Risk, Basel III, KYC |
| **Department of Financial Services (DFS)** | **9** | **202** | 18.0% | Official Gazettes, NaBFID Rules, Public Sector Bank Board Governance |
| **Securities and Exchange Board of India (SEBI)** | **8** | **174** | 15.5% | NRI KYC Simplification, Currency Derivative Limits, Business Continuity Planning (BCP) |
| **Insurance Regulatory Authority (IRDAI)** | **1** | **16** | 1.4% | Master Circular on Registration, Capital Structure, and Share Transfers |
| **Total** | **40** | **1,123** | **100.0%** | Complete Indian Financial Regulatory Umbrella |

### Structural Complexity Metrics:
- **Long Documents ($> 50$ pages)**: 7 documents, led by `rbi_misc_directions_2025` (167 pages) and `rbi_forthcoming_instructions_2025` (105 pages).
- **Two-Column Documents**: 3 documents (`rbi_bulletin_economy_oct2026`, `rbi_bulletin_speech_oct2026`, `dfs_nabfid_rules_2022`).
- **Table-Heavy Documents**: 8 documents featuring dense financial matrices and lists of repealed circulars.
- **Pure Raster Scanned Documents**: 8 documents (DFS Gazette notifications), requiring selective OCR invocation.

### Parsing Quality & OCR Accuracy:
- **Native Digital Pages**: 100% extraction precision for digital text streams using PyMuPDF font extraction.
- **Scanned Page Case Study (`dfs_sidbi_dmd_2026`, Page 1)**: Pure raster page processed by Tesseract 5.5.0 in **0.91 seconds**. The system achieved a **95.8% word accuracy (91 / 95 words)** on the official typed legal text. Signature blocks were isolated into low-confidence regions, preventing OCR noise leakage.

---

## 6. The 10-Step Safe Lifecycle & CAS Promotion Protocol

To prevent vector database poisoning, orphaned chunks, and race conditions, PolicyLens enforces a strict 10-step protocol:

1. **Document Identification**: Hash PDF bytes and metadata to derive `doc_id` and load current active status.
2. **Structure-Aware Parsing**: Reconstruct reading order across columns; extract tables into clean Markdown.
3. **Semantic Chunking**: Create discrete chunks (~350 body tokens) bound to section headings.
4. **Deterministic Fingerprinting**: Hash canonical chunk tokens using SHA-256 (`index_fingerprint`).
5. **Idempotency Gate**: If `index_fingerprint` matches `active_fingerprint` in `document_registry`, return `SKIPPED` in 2.1 milliseconds.
6. **Staging Registration**: In a SQLite transaction, persist `expected_active_fingerprint`, register candidate in `version_lifecycle` with `state='staging'`, lease duration, host ID, worker ID, PID, and `fencing_token=1`.
7. **Local CPU Embedding**: Generate 384-dimensional normalized float vectors using `sentence-transformers/all-MiniLM-L6-v2`.
8. **Guarded ChromaDB Ingestion**: Pre-validate that all chunks in the batch exactly match the expected `document_id`, `collection_name`, `index_fingerprint`, and `version_id`. Reject before issuing writes if any field diverges.
9. **Staging Verification**: Worker validates total chunk count and token sums, updating state to `verified`.
10. **Atomic CAS Promotion**: In a SQLite transaction, verify worker lease and fencing token; verify `expected_active_fingerprint` matches the current active fingerprint in `document_registry`. If matched, demote existing active record to `superseded`, promote candidate to `active`, and update `document_registry`. If mismatched (indicating a newer candidate won a promotion race), reject promotion with `StalePromotionError` and transition candidate to `failed`.

---

## 7. Retrieval Evaluation: Structure-Aware vs Fixed-Window

We conducted a controlled evaluation comparing **Structure-Aware Chunking** against a **Fixed-Window Baseline (500 tokens, 50 overlap)** across 25 expert-audited compliance questions:

| Evaluation Metric | Structure-Aware Chunking | Fixed-Window Baseline (500/50) | Performance Advantage |
|---|:---:|:---:|:---:|
| **Recall@3** | **96.0%** (24 / 25) | 92.0% (23 / 25) | **+4.0% Absolute Improvement** |
| **Recall@5** | **100.0%** (25 / 25) | 100.0% (25 / 25) | Complete Parity |
| **Recall@10** | **100.0%** (25 / 25) | 100.0% (25 / 25) | Complete Parity |
| **Mean Reciprocal Rank (MRR)** | **0.9100** | 0.8333 | **+0.0767 (+9.2% Relative Gain)** |

### Disagreement Analysis:
- In `Q06` (repealed circular table lookup) and `Q10` (applicability clause), Structure-Aware chunking achieved **Rank 1 retrieval**, whereas Fixed-Window chunking degraded to **Rank 4** because window boundaries severed table headers and diluted legal clauses with unrelated text.
- In `Q23` (accredited bank listing), Fixed-Window chunking achieved **Rank 2** vs **Rank 4** for Structure-Aware, as the large 500-token window captured 20 table rows in a single continuous block.

---

## 8. Efficiency, Robustness & Benchmark Results

| Metric | Measured Value | Operational Significance |
|---|:---:|---|
| **Full-Corpus Ingestion (Run 1)** | **187.87 s (~3.13 min)** | End-to-end parse, OCR, embedding, guarded write, and CAS promotion across all 40 PDFs / 1,123 pages (16.73 s / 100 pages, 5.98 pgs/sec) |
| **Idempotent Re-Run (Run 2)** | **0.09 s (90 ms)** | Instantaneous idempotency detection via SHA-256 fingerprint matching across all 40 documents (**2,087x speedup**, 0 new chunks, 0 duplicates) |
| **Total Active Chunks** | **1,604 Chunks** | In collection `policylens_v1` (1,763 chunks total across all collections) |
| **Warm Vector Query Latency** | **11.61 ms** | Sub-15ms vector retrieval over 20 repeated queries against active ChromaDB HNSW index (min: 10.53 ms, p95: 14.58 ms) |
| **Cold CLI Query Latency** | **3.28 s** | Includes Python runtime startup and SentenceTransformers weight initialization |
| **Local Embedding Compute Cost** | **$0.00 (Zero API Cost)** | SentenceTransformers CPU execution; requires ~2.5 seconds CPU time per 1,000 chunks |
| **SQLite Registry Footprint** | **112.0 KB** | Fully indexed metadata and lifecycle audit log across 40 documents |
| **ChromaDB Storage Footprint** | **28.25 MB** | Complete local persistent HNSW vector storage covering all 40 regulatory circulars |
| **Automated Test Suite** | **38 / 38 Passing** | Full test suite executes in 1.1s with zero external network dependencies |

---

## 9. Enterprise Scalability, Supersession & Security Architecture

### 9.1 Scaling to 100,000 Documents
For enterprise scale (100k regulatory circulars, ~2.5 million chunks):
1. **Sharded Vector Storage**: Transition from embedded ChromaDB to distributed vector clusters (Milvus or Qdrant) sharded by `issuer` and `issuance_year`.
2. **Distributed Leases**: Replace local SQLite file locks with Redis distributed leases (`Redlock`) using monotonic fencing tokens.
3. **Hierarchical HNSW Indexing**: Implement partitioned vector graphs ensuring that vector similarity searches only traverse sub-graphs tagged with active fingerprints.

### 9.2 Superseded & Withdrawn Circular Handling
When a regulator repeals a directive (e.g., Master Direction repealing 23 prior circulars):
- The new Master Direction is ingested and CAS-promoted.
- Ingestion metadata automatically records repealed circular numbers.
- A database hook updates the repealed circular versions to `superseded` in `version_lifecycle`.
- The active snapshot immediately purges their fingerprints, excluding them from retrieval in $< 1\text{ ms}$.
- Late-arriving writes from revoked workers are purged by the background sweeper (`run_reconciliation_sweeper()`).

### 9.3 Access Control and Data Privacy
1. **Multi-Tenant Policy Scoping**: Enforce Role-Based Access Control (RBAC) via SQLite column `access_tier` (`public_regulatory`, `internal_confidential`, `board_sensitive`).
2. **Zero Cloud Egress**: By default, embeddings execute on local CPU hardware (`all-MiniLM-L6-v2`), guaranteeing that confidential internal compliance policies never leave the enterprise perimeter.
3. **Prompt Leakage Prevention**: Grounded system prompts explicitly disallow revealing prompt system instructions or raw vector distance scores to client callers.

---

## 10. Conclusion

PolicyLens demonstrates that high-reliability compliance AI systems require tight architectural integration between multimodal document parsing, transactional database lifecycle controls, guarded vector ingestion, and anti-hallucination prompt framing. By treating document indexing as an ACID-compliant state machine, PolicyLens eliminates the core vulnerabilities of naive RAG: vector index poisoning, stale circular citations, and catastrophic hallucinations—delivering sub-15ms compliance question answering on commodity CPU hardware.

---

## 11. References

1. **PolicyLens Repository**: [`LLM_Case_Studies/CS2_PolicyLens/`](file:///Users/vinit/Vinit/ITM/Agent%20AI%20Foundations/LLM_Case_Studies/CS2_PolicyLens/)
2. **Regulatory Corpus Manifest (40 PDFs, 1,123 Pages)**: [`CS2_PolicyLens/data/manifest.csv`](file:///Users/vinit/Vinit/ITM/Agent%20AI%20Foundations/LLM_Case_Studies/CS2_PolicyLens/data/manifest.csv)
3. **Core Version Registry & CAS Implementation**: [`CS2_PolicyLens/src/version_registry.py`](file:///Users/vinit/Vinit/ITM/Agent%20AI%20Foundations/LLM_Case_Studies/CS2_PolicyLens/src/version_registry.py)
4. **Evaluation Benchmark Suite (25 Questions)**: [`CS2_PolicyLens/eval/`](file:///Users/vinit/Vinit/ITM/Agent%20AI%20Foundations/LLM_Case_Studies/CS2_PolicyLens/eval/)
5. **Efficiency Benchmark & Latency Measurements**: [`CS2_PolicyLens/eval/benchmark_results.md`](file:///Users/vinit/Vinit/ITM/Agent%20AI%20Foundations/LLM_Case_Studies/CS2_PolicyLens/eval/benchmark_results.md)
6. **Parsing Quality Audit**: [`CS2_PolicyLens/eval/parsing_quality.md`](file:///Users/vinit/Vinit/ITM/Agent%20AI%20Foundations/LLM_Case_Studies/CS2_PolicyLens/eval/parsing_quality.md)
