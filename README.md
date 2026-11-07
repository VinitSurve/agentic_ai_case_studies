# Agentic AI & LLM Case Studies

This repository contains production-grade case studies developed for the **Agent AI Foundations** curriculum, focusing on real-world enterprise LLM architectures, prompt engineering, information extraction, multimodal parsing, versioned vector lifecycle indexing, and agentic workflows.

---

## 1. Case Studies Overview

| Case Study | Subtitle & Domain | Primary Technology Stack | Evaluation Scope | Submission Status |
|---|---|---|---|:---:|
| **[CS1 – ClaimFast](CS1_ClaimFast/)** | Automated Motor Insurance Claim Triage & Entity Extraction | `qwen/qwen3.8-27b`, Groq Cloud, Python 3.11, ReportLab | 900 evaluation jobs (60 held-out test messages × 5 prompt configurations × 3 runs) | **100% COMPLETE & AUDITED** (Report, Code & Results Published) |
| **[CS2 – PolicyLens](CS2_PolicyLens/)** | Regulatory Document Ingestion, Lifecycle Indexing & Grounded RAG QA | PyMuPDF, pdfplumber, Tesseract OCR, ChromaDB, SentenceTransformers CPU | 40 official Indian regulatory PDFs (1,123 pages, RBI/SEBI/IRDAI/DFS) | **100% COMPLETE & VERIFIED** (All 38 Unit Tests Passing, CLI & RAG Verified) |

---

## 2. Case Study 1: ClaimFast (Motor Insurance FNOL Triage)

### Executive Objective
To build an automated First Notice of Loss (FNOL) triage and entity extraction system capable of parsing unstructured, noisy, and code-mixed customer claim messages in India directly into a strict 9-field schema without external tools.

### Core Highlights & Findings
- **900 Controlled Evaluation Jobs**: 60 held-out test messages (`TEST001`–`TEST060`) evaluated across 5 prompt configurations (`zero_shot`, `few_shot_k3`, `few_shot_k5`, `few_shot_k8`, `structured_reasoning`) over 3 repeated runs at temperature 0.0.
- **Safety Triage Precision**: **100.0% precision and recall on high urgency and bodily injury triage** (240 / 240 high-urgency instances). Zero injury claims were missed.
- **Category Classification**: **0.9844 Macro-F1** across 6 claim categories (`own_damage`, `third_party_liability`, `theft`, `total_loss`, `glass_only`, `not_a_claim`).
- **Structured Reasoning Breakthrough**: `structured_reasoning` achieved the highest classification Macro-F1 (**0.9870**) and was the *only* strategy to correctly adjudicate the complex `TEST005` door-scratch edge case under Rule A, while running **23.8% faster** (510ms) and costing **31.8% less** ($0.38/1k claims) than few-shot $k=8$.

### Deliverables
- **Publication PDF Report**: [`CS1_ClaimFast/report/report_CS1.pdf`](CS1_ClaimFast/report/report_CS1.pdf) (5-page PDF)
- **Technical Markdown Report**: [`CS1_ClaimFast/REPORT.md`](CS1_ClaimFast/REPORT.md)
- **Dataset**: [`CS1_ClaimFast/data/test.jsonl`](CS1_ClaimFast/data/test.jsonl) (60 records) and [`CS1_ClaimFast/data/dev.jsonl`](CS1_ClaimFast/data/dev.jsonl) (20 records)
- **Prompt Library**: Standardized prompts in [`CS1_ClaimFast/prompts/`](CS1_ClaimFast/prompts/)
- **Raw Outputs & Flattened Results**: [`CS1_ClaimFast/outputs/results.csv`](CS1_ClaimFast/outputs/results.csv) (900 rows)
- **Error Analysis**: [`CS1_ClaimFast/error_analysis/error_analysis.csv`](CS1_ClaimFast/error_analysis/error_analysis.csv) (272 audited failures)
- **Interactive Demo**: [`CS1_ClaimFast/demo/run_demo.py`](CS1_ClaimFast/demo/run_demo.py) & [`CS1_ClaimFast/demo/demo_script.md`](CS1_ClaimFast/demo/demo_script.md)

---

## 3. Case Study 2: PolicyLens (Regulatory Ingestion & Grounded RAG)

### Executive Objective
To build a fault-tolerant regulatory document ingestion, lifecycle-aware indexing, and grounded question-answering engine for Indian financial circulars and master directions issued by RBI, SEBI, IRDAI, and DFS.

### Core Highlights & Findings
- **Multimodal Layout-Aware PDF Extraction**: Reconstructs reading order across single- and two-column layouts; detects full-width headers; extracts tables with Markdown formatting; triggers Tesseract OCR selectively on raster content.
- **Transactional SQLite Lifecycle Registry**: 10-step safe lifecycle state machine (`staging` $\to$ `verified` $\to$ `active` / `superseded` / `revoked` / `failed`) with atomic Compare-And-Swap (CAS) candidate promotion, worker fencing tokens, and process-start lease validation.
- **Guarded ChromaDB Ingestion & Active-Only Retrieval**: Pre-validates vector metadata before writes; ensures queries retrieve strictly from active document fingerprints.
- **Grounded RAG Question Answering (`--ask`)**: Strict anti-hallucination prompting, complete source provenance (Document ID, Page, Section, Score), and automatic fallback between cloud LLMs (Groq) and deterministic extractive summaries. Zero LLM calls on out-of-domain queries.
- **Automated Verification**: **38 unit and integration tests passing** in 1.13 seconds without external network dependencies.

### Deliverables
- **Technical Markdown Report**: [`CS2_PolicyLens/REPORT.md`](CS2_PolicyLens/REPORT.md)
- **Unified CLI Entrypoint**: [`CS2_PolicyLens/index.py`](CS2_PolicyLens/index.py)
- **Corpus Manifest**: [`CS2_PolicyLens/data/manifest.csv`](CS2_PolicyLens/data/manifest.csv) (40 PDFs, 1,123 pages)
- **Automated Test Suite**: 38 tests in [`CS2_PolicyLens/tests/`](CS2_PolicyLens/tests/)

---

## 4. Repository Structure

```text
agentic_ai_case_studies/
├── README.md                      # Root documentation (this file)
├── .gitignore                     # Git hygiene (zero credentials, no runtime DBs/logs)
├── CS1_ClaimFast/                 # Case Study 1: Complete & Audited
│   ├── README.md                  # Comprehensive project documentation
│   ├── REPORT.md                  # Standalone technical case study report
│   ├── requirements.txt           # Dependencies (groq, reportlab, python-dotenv)
│   ├── data/                      # 80 dual-audited claim records (dev + test)
│   ├── prompts/                   # 5 prompt engineering configurations
│   ├── code/                      # Evaluation runner, metrics engine, and Groq managers
│   ├── outputs/                   # 900 evaluated jobs (results.csv & evaluation_results.jsonl)
│   ├── error_analysis/            # 272 audited failure diagnoses
│   ├── demo/                      # Interactive CLI demo and 12 verified screenshots
│   └── report/                    # Publication PDF report (report_CS1.pdf)
└── CS2_PolicyLens/                # Case Study 2: Complete & Verified
    ├── README.md                  # Comprehensive project documentation
    ├── REPORT.md                  # Standalone technical case study report
    ├── index.py                   # Root CLI (--index, --status, --query, --ask)
    ├── requirements.txt           # Dependencies (PyMuPDF, pdfplumber, ChromaDB, SentenceTransformers)
    ├── data/                      # Manifest (40 PDFs, 1,123 pages) and registry DB
    ├── src/                       # Layout parser, chunker, embeddings, lifecycle, and RAG QA
    └── tests/                     # 38 passing unit and integration tests
```

---

## 5. Environment & Quickstart

Clone the repository and install dependencies:
```bash
git clone https://github.com/VinitSurve/agentic_ai_case_studies.git
cd agentic_ai_case_studies

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies for both case studies
pip install -r CS1_ClaimFast/requirements.txt
pip install -r CS2_PolicyLens/requirements.txt
```

### Run Case Study 1 (ClaimFast):
```bash
# Run interactive 3-minute demonstration
python CS1_ClaimFast/demo/run_demo.py

# Re-compute verified metrics from 900 raw jobs
python CS1_ClaimFast/code/compute_metrics.py
```

### Run Case Study 2 (PolicyLens):
```bash
# Run complete test suite (38 passing tests in 1.1s)
python -m unittest discover -s CS2_PolicyLens/tests -p "test_*.py" -v

# Ask a grounded regulatory question
python CS2_PolicyLens/index.py --ask "What are the rules for recovery of excess or wrong pension payments?"

# View active document registry status
python CS2_PolicyLens/index.py --status
```

---

## 6. Author & Attribution

- **Lead AI Engineer**: Vinit Surve (`survevinit5006@gmail.com`)
- **Institution**: ITM – Agent AI Foundations
- **GitHub**: [https://github.com/VinitSurve/agentic_ai_case_studies](https://github.com/VinitSurve/agentic_ai_case_studies)
