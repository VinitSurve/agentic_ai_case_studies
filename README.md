# Agentic AI & LLM Case Studies

This repository contains production-grade case studies developed for the **Agent AI Foundations** curriculum, focusing on real-world enterprise LLM architectures, prompt engineering, information extraction, multimodal parsing, and agentic workflows.

---

## 1. Case Studies Overview

| Case Study | Subtitle & Domain | Primary Technology Stack | Evaluation Scope | Current Status |
|---|---|---|---|:---:|
| **[CS1 – ClaimFast](CS1_ClaimFast/)** | Automated Motor Insurance Claim Triage & Entity Extraction | `qwen/qwen3.8-27b`, Groq Cloud, Python 3.11, ReportLab | 900 evaluation jobs (60 held-out test messages × 5 prompt configurations × 3 runs) | **100% COMPLETE & AUDITED** |
| **[CS2 – PolicyLens](CS2_PolicyLens/)** | Regulatory Document Intelligence & Retrieval Engine | PyMuPDF, Tesseract OCR, ChromaDB, BGE-large embeddings | 40 official Indian regulatory PDFs (1,123 pages, RBI/SEBI/IRDAI) | **PHASES 1 & 2 COMPLETE** (Corpus & Manifest Verified) |

---

## 2. Case Study 1: ClaimFast (Motor Insurance FNOL Triage)

### Executive Objective
To build an automated First Notice of Loss (FNOL) triage and entity extraction system capable of parsing unstructured, noisy, and code-mixed customer claim messages in India directly into a strict 9-field schema without external tools.

### Core Highlights & Findings
- **900 Controlled Evaluation Jobs**: 60 held-out test messages (`TEST001`–`TEST060`) evaluated across 5 prompt configurations (`zero_shot`, `few_shot_k3`, `few_shot_k5`, `few_shot_k8`, `structured_reasoning`) over 3 repeated runs at temperature 0.0.
- **Safety Triage Precision**: **100.0% precision and recall on high urgency and bodily injury triage** (240 / 240 high-urgency instances). Zero injury claims were missed.
- **Category Classification**: **0.9844 Macro-F1** across 6 claim categories (`own_damage`, `third_party_liability`, `theft`, `total_loss`, `glass_only`, `not_a_claim`).
- **Structured Reasoning Breakthrough**: `structured_reasoning` achieved the highest classification Macro-F1 (**0.9870**) and was the *only* strategy to correctly adjudicate the complex `TEST005` door-scratch edge case under Rule A, while running **23.8% faster** (510ms) and costing **31.8% less** ($0.38/1k claims) than few-shot $k=8$.
- **Deliverables**:
  - Publication Report: [`CS1_ClaimFast/report/report_CS1.pdf`](CS1_ClaimFast/report/report_CS1.pdf) (5-page PDF)
  - Dataset: [`CS1_ClaimFast/data/test.jsonl`](CS1_ClaimFast/data/test.jsonl) (60 records) and [`CS1_ClaimFast/data/dev.jsonl`](CS1_ClaimFast/data/dev.jsonl) (20 records)
  - Prompt Library: Standardized prompts in [`CS1_ClaimFast/prompts/`](CS1_ClaimFast/prompts/)
  - Raw Outputs & Flattened Results: [`CS1_ClaimFast/outputs/results.csv`](CS1_ClaimFast/outputs/results.csv) (900 rows)
  - Error Analysis: [`CS1_ClaimFast/error_analysis/error_analysis.csv`](CS1_ClaimFast/error_analysis/error_analysis.csv) (272 audited failures)
  - Interactive Demo: [`CS1_ClaimFast/demo/run_demo.py`](CS1_ClaimFast/demo/run_demo.py)

---

## 3. Case Study 2: PolicyLens (Regulatory Document Intelligence)

### Executive Objective
To develop a high-accuracy, production-ready regulatory question-answering and policy search engine for Indian financial circulars and master directions issued by RBI, SEBI, IRDAI, and the Ministry of Finance (DFS).

### Architectural Overview
- **Hybrid Parsing & Layout Analysis**:
  - Two-column reading order reconstruction with full-width header detection.
  - OCR fallback using Tesseract for scanned regulatory documents and embedded image stamps.
  - Structured table extraction with row-level chunk preservation.
- **Chunking & Indexing**:
  - Fixed-size token chunking (300–800 tokens with overlap) using tokenizers.
  - Structure-aware chunking preserving regulatory clauses and headings.
  - Active/superseded document version staging and atomic pointer swapping.
- **Current Completion Status**:
  - **Phase 1 (Environment & Architecture Setup)**: Verified PyMuPDF, Tesseract OCR, ChromaDB persistence, BGE embeddings, and CPU embedding path.
  - **Phase 2 (Corpus Collection & Corrective Audit)**: Harvested and verified 40 public Indian regulatory PDFs (1,123 pages, 30.75 MB), fully catalogued in [`CS2_PolicyLens/data/manifest.csv`](CS2_PolicyLens/data/manifest.csv).
  - **Phase 3 (Next Phase)**: Implementation of the PDF parser, layout analyzer, and OCR engine.

---

## 4. Repository Structure

```text
agentic_ai_case_studies/
├── README.md                      # Root documentation (this file)
├── .gitignore                     # Git hygiene (zero credentials, no venv/logs)
├── CS1_ClaimFast/                 # Case Study 1: Complete & Audited
│   ├── README.md
│   ├── requirements.txt
│   ├── .env.example
│   ├── data/
│   ├── prompts/
│   ├── code/
│   ├── outputs/
│   ├── error_analysis/
│   ├── demo/
│   └── report/
│       └── report_CS1.pdf         # 5-page publication-quality final report
└── CS2_PolicyLens/                # Case Study 2: Phases 1 & 2 Complete
    ├── data/
    │   ├── manifest.csv           # 40 audited regulatory documents
    │   └── pdfs/                  # Downloaded regulatory circulars
    ├── src/
    └── requirements.txt
```

---

## 5. Environment & Setup

Clone the repository:
```bash
git clone https://github.com/VinitSurve/agentic_ai_case_studies.git
cd agentic_ai_case_studies
```

Create and activate a virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r CS1_ClaimFast/requirements.txt
```

---

## 6. Author & Attribution

- **Lead AI Engineer**: Vinit Surve (`survevinit5006@gmail.com`)
- **Institution**: ITM – Agent AI Foundations
- **GitHub**: [https://github.com/VinitSurve/agentic_ai_case_studies](https://github.com/VinitSurve/agentic_ai_case_studies)
