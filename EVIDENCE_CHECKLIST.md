# Submission Evidence & Screenshot Checklist

**Repository**: `agentic_ai_case_studies`  
**Date**: November 7, 2026  
**Curriculum**: Agent AI Foundations  
**Author**: Vinit Surve (`survevinit5006@gmail.com`)  

This document catalogues all visual, tabular, and machine-generated evidence supporting the final submission of **CS1: ClaimFast** and **CS2: PolicyLens**.

---

## 1. Case Study 1: ClaimFast (12 Verified Screenshots on Disk)

All 12 screenshots are stored locally at:  
[`CS1_ClaimFast/demo/screenshots/ClaimFast_12_Screenshots/`](file:///Users/vinit/Vinit/ITM/Agent%20AI%20Foundations/LLM_Case_Studies/CS1_ClaimFast/demo/screenshots/ClaimFast_12_Screenshots/)

| Category | Screenshot File | Dimensions / Size | Content & Verification Evidence |
|---|---|---|---|
| **Architecture** | [`01_project_location.png`](CS1_ClaimFast/demo/screenshots/ClaimFast_12_Screenshots/01_project_location.png) | 64.2 KB | Terminal showing active repository path and working environment. |
| **Architecture** | [`02_project_folder_structure.png`](CS1_ClaimFast/demo/screenshots/ClaimFast_12_Screenshots/02_project_folder_structure.png) | 68.7 KB | Visual inspection of directory tree (`code/`, `data/`, `prompts/`, `outputs/`). |
| **Dataset** | [`03_dataset_split_and_sample_records.png`](CS1_ClaimFast/demo/screenshots/ClaimFast_12_Screenshots/03_dataset_split_and_sample_records.png) | 230.6 KB | Inspection of `dev.jsonl` (20 records) and held-out `test.jsonl` (60 records). |
| **Prompt Engineering** | [`04_prompt_templates.png`](CS1_ClaimFast/demo/screenshots/ClaimFast_12_Screenshots/04_prompt_templates.png) | 93.9 KB | Prompt template definitions for Zero-Shot, Few-Shot, and Structured Reasoning. |
| **Execution** | [`05_evaluation_run_status.png`](CS1_ClaimFast/demo/screenshots/ClaimFast_12_Screenshots/05_evaluation_run_status.png) | 217.3 KB | Batch execution monitor displaying 900 jobs completed across 3 runs. |
| **Execution** | [`06_detailed_evaluation_output.png`](CS1_ClaimFast/demo/screenshots/ClaimFast_12_Screenshots/06_detailed_evaluation_output.png) | 446.7 KB | Raw evaluation runner output logs and JSON generation details. |
| **Evaluation Output** | [`07_evaluation_analysis_part_1.png`](CS1_ClaimFast/demo/screenshots/ClaimFast_12_Screenshots/07_evaluation_analysis_part_1.png) | 289.8 KB | Schema validity (99.44%) and individual field accuracy aggregations. |
| **Evaluation Output** | [`08_evaluation_analysis_part_2.png`](CS1_ClaimFast/demo/screenshots/ClaimFast_12_Screenshots/08_evaluation_analysis_part_2.png) | 359.6 KB | Macro-F1 breakdown (`claim_type`: 0.9844, `urgency`: 0.9188) and 100% safety F1. |
| **Evaluation Output** | [`09_evaluation_analysis_part_3.png`](CS1_ClaimFast/demo/screenshots/ClaimFast_12_Screenshots/09_evaluation_analysis_part_3.png) | 310.1 KB | Latency analysis (510ms for structured reasoning) and cost comparison ($0.38/1k). |
| **Error Analysis** | [`10_error_analysis_csv_preview.png`](CS1_ClaimFast/demo/screenshots/ClaimFast_12_Screenshots/10_error_analysis_csv_preview.png) | 300.5 KB | Tabular inspection of `error_analysis.csv` detailing the 272 audited failures. |
| **Final Report** | [`11_report_benchmark_and_safety_tables.png`](CS1_ClaimFast/demo/screenshots/ClaimFast_12_Screenshots/11_report_benchmark_and_safety_tables.png) | 627.2 KB | PDF report pages presenting benchmark tables and safety triage metrics. |
| **Final Report** | [`12_report_error_analysis_and_consistency.png`](CS1_ClaimFast/demo/screenshots/ClaimFast_12_Screenshots/12_report_error_analysis_and_consistency.png) | 519.3 KB | PDF report pages detailing failure analysis, casing impact, and 3-run variance. |

---

## 2. Case Study 2: PolicyLens (Machine-Generated Evidence & Logs)

PolicyLens features complete machine-generated text evidence and verified live outputs on disk:

| Evidence Code | Artifact Type | File Location on Disk | Measured Content / Output Verified |
|:---:|---|---|---|
| **PL-LOG-01** | First-Run Ingestion Log | [`CS2_PolicyLens/logs/submission_first_run.log`](CS2_PolicyLens/logs/submission_first_run.log) | Real execution of `sebi_currency_deriv_limits_2026.pdf` (3 pages) in **8.76s** (`STATUS: SUCCESS`). |
| **PL-LOG-02** | Second-Run Idempotency Log | [`CS2_PolicyLens/logs/submission_second_run.log`](CS2_PolicyLens/logs/submission_second_run.log) | Idempotent re-run completed in **0.0021s (2.1 ms)** (`STATUS: SKIPPED`). |
| **PL-EVAL-01** | 25-Question Benchmark | [`CS2_PolicyLens/eval/questions.csv`](CS2_PolicyLens/eval/questions.csv) | 25 compliance questions (14 text, 6 table-lookup, 5 paraphrased) with verified gold pages. |
| **PL-EVAL-02** | Retrieval Results Matrix | [`CS2_PolicyLens/eval/retrieval_results.csv`](CS2_PolicyLens/eval/retrieval_results.csv) | Question-by-question comparative ranking across `policylens_structure` and `policylens_fixed`. |
| **PL-EVAL-03** | Quantitative Metrics | [`CS2_PolicyLens/eval/metrics.json`](CS2_PolicyLens/eval/metrics.json) | Structure-aware (Recall@3: **96.0%**, MRR: **0.9100**) vs Fixed-window (Recall@3: **92.0%**, MRR: **0.8333**). |
| **PL-AUDIT-01** | Corpus Audit Document | [`CS2_PolicyLens/eval/corpus_audit.md`](CS2_PolicyLens/eval/corpus_audit.md) | Exhaustive structural audit of all 40 PDFs (1,123 pages) across RBI, DFS, SEBI, and IRDAI. |
| **PL-AUDIT-02** | Parsing & OCR Audit | [`CS2_PolicyLens/eval/parsing_quality.md`](CS2_PolicyLens/eval/parsing_quality.md) | 10-page manual layout audit; Tesseract OCR **95.8% word accuracy** on `dfs_sidbi_dmd_2026`. |
| **PL-AUDIT-03** | Efficiency & Latency Audit | [`CS2_PolicyLens/eval/benchmark_results.md`](CS2_PolicyLens/eval/benchmark_results.md) | Query latency distribution (mean **10.3 ms**), zero API costs, storage footprints. |
| **PL-REP-01** | Publication PDF Report | [`CS2_PolicyLens/report/report_CS2.pdf`](CS2_PolicyLens/report/report_CS2.pdf) | Authoritative 5-page publication-quality ReportLab PDF report with tables and analysis. |
| **PL-CLI-01** | Assignment Ingestion CLI | [`CS2_PolicyLens/ingest.py`](CS2_PolicyLens/ingest.py) | Thin wrapper supporting `--pdf <path>` and `--status`. |
| **PL-CLI-02** | Assignment Search CLI | [`CS2_PolicyLens/search.py`](CS2_PolicyLens/search.py) | Thin wrapper supporting `--query <q>`, `--ask <q>`, and `--filter issuer=RBI`. |

---

## 3. PolicyLens Visual Capture Guide (If Submitting PNG Screenshots)

If manual screenshot images are required for submission, capture the following 6 terminal screens:

### Screenshot PL-01: Ingestion & CAS Promotion
- **Command**:
  ```bash
  python CS2_PolicyLens/ingest.py --pdf CS2_PolicyLens/data/pdfs/rbi_disbursement_pension_2026.pdf --doc-id rbi_pension_2026
  ```
- **Evidence**: Demonstrates successful parsing, embedding, guarded write, and CAS promotion.

### Screenshot PL-02: Active Document Registry Status
- **Command**:
  ```bash
  python CS2_PolicyLens/ingest.py --status
  ```
- **Evidence**: Displays all active document versions, fingerprints, chunk counts, and promotion timestamps in SQLite.

### Screenshot PL-03: Filtered Regulatory Search (`--filter issuer=RBI`)
- **Command**:
  ```bash
  python CS2_PolicyLens/search.py --query "pension recovery rules" --filter issuer=RBI
  ```
- **Evidence**: Displays metadata filtering matching RBI documents and retrieved chunks with cosine scores.

### Screenshot PL-04: Grounded Compliance Question Answering (`--ask`)
- **Command**:
  ```bash
  python CS2_PolicyLens/search.py --ask "What are the rules for recovery of excess or wrong pension payments?"
  ```
- **Evidence**: Displays the grounded regulatory answer and structured provenance citations (Doc ID, Page, Section, Score).

### Screenshot PL-05: Out-of-Domain Zero-Hallucination Fallback
- **Command**:
  ```bash
  python CS2_PolicyLens/search.py --ask "What is the speed of light in vacuum and the capital of Mars?"
  ```
- **Evidence**: Demonstrates `INSUFFICIENT_CONTEXT` fallback without making external LLM calls.

### Screenshot PL-06: Complete Automated Test Suite (38 Tests Passing)
- **Command**:
  ```bash
  python -m unittest discover -s CS2_PolicyLens/tests -p "test_*.py" -v
  ```
- **Evidence**: Confirms 100% test passage (38 / 38 unit and integration tests) in 1.12 seconds on local CPU.
