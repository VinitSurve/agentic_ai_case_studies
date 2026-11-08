# Case Study 2: PolicyLens Demo & Screenshot Submission Checklist

This folder is reserved for submission media (video walkthrough and GUI/CLI screenshots).

## Required Deliverables:
1. **Video Walkthrough (MP4 / WebM / Loom Link)**:
   - 3 to 5 minutes demonstrating:
     a) Batch ingestion of 40 PDFs into `policylens_v1` using `ingest.py`
     b) Idempotent re-run showing 0 duplicate chunks in 0.09s
     c) Filtered search with `--filter issuer=RBI` showing title, page range, and section
     d) Grounded question answering with `--ask` displaying exact provenance citations
     e) Out-of-scope question showing honest fallback disclaimer (zero hallucination)
2. **Demo Screenshots**:
   - `screenshot_01_ingestion_summary.png`: CLI output of batch ingestion summary.
   - `screenshot_02_idempotency_check.png`: CLI output of 2,087x speedup and 0 new chunks.
   - `screenshot_03_filtered_search.png`: Filtered search output with title, page, section.
   - `screenshot_04_rag_qa_provenance.png`: Grounded answer with source citations.
   - `screenshot_05_honest_fallback.png`: Out-of-scope honest fallback response.

*Note: Execution scripts and step-by-step commands are documented in `evidence/DEMO_STEPS.md`.*
