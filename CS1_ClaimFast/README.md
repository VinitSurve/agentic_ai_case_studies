# ClaimFast – Automated Motor Insurance Claim Triage & Entity Extraction

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Model: qwen3.8-27b](https://img.shields.io/badge/Model-qwen%2Fqwen3.8--27b-orange.svg)](https://console.groq.com/docs/models)
[![Evaluation Jobs](https://img.shields.io/badge/Evaluation%20Jobs-900%20%2F%20900-brightgreen.svg)]()
[![Schema Validity](https://img.shields.io/badge/Schema%20Validity-99.44%25-green.svg)]()
[![High-Urgency F1](https://img.shields.io/badge/Safety%20F1-1.0000-brightgreen.svg)]()

**ClaimFast** is an automated motor insurance First Notice of Loss (FNOL) triage and entity extraction benchmark designed for high-noise, code-mixed, and vernacular customer claim messages in India.

This project evaluates the zero-shot, few-shot, and structured reasoning capabilities of open-weights LLMs (`qwen/qwen3.8-27b` via Groq Cloud) across **900 controlled evaluation jobs** ($5 \text{ prompt strategies} \times 60 \text{ held-out test messages} \times 3 \text{ repeated runs}$).

---

## 1. Problem Formulation

Motor insurance customer communications in India are heavily unstructured and present unique NLP challenges:
- **Code-mixing & Hinglish transliterations** (*"auto driver ko chot aayi hai hospital le gaye"*, *"raat ko blind turn pe divider se takra gayi"*).
- **Insurance Legal Boundaries**:
  - *Rule A (Personal Belongings vs Component Theft)*: Theft of personal bags from a vehicle is not vehicle theft; if only glass is broken, it is `glass_only`; if vehicle body panels are also scratched, it is `own_damage`.
  - *Rule B (Untraced Hit-and-Run)*: Collisions caused by untraced fled third parties are classified as `own_damage`.
  - *Rule C (Suspected vs Confirmed Total Loss)*: A surveyor saying it *"may be a total loss"* remains `own_damage` until officially confirmed as a constructive total loss.
  - *Rule D (Strict Negative Standards)*: Booleans are `false` only with explicit negative evidence; unmentioned fields map strictly to `null`.
- **Zero Tooling / Direct Extraction**: Processing noisy text directly into a strict 9-field JSON object without external tools or search engines.

---

## 2. Directory Structure

```text
CS1_ClaimFast/
├── README.md                      # Comprehensive project documentation
├── requirements.txt               # Dependencies (groq, reportlab, python-dotenv)
├── .env.example                   # API key configuration template
├── data/
│   ├── dev.jsonl                  # 20 development records (few-shot exemplar pool)
│   ├── test.jsonl                 # 60 held-out test records (evaluation benchmark)
│   ├── schema.md                  # 9-field schema definition and rules
│   ├── labelling_guide.md         # Comprehensive ground-truth labelling guidelines
│   └── dataset_plan.md            # Dataset composition and generation plan
├── prompts/
│   ├── zero_shot.txt              # Strategy A: Direct baseline extraction
│   ├── few_shot_k3.txt            # Strategy B1: 3 in-context exemplars
│   ├── few_shot_k5.txt            # Strategy B2: 5 in-context exemplars
│   ├── few_shot_k8.txt            # Strategy B3: 8 in-context exemplars
│   ├── structured_reasoning.txt   # Strategy C: Internal verification checklist
│   └── README.md                  # Methodological prompt progression guide
├── code/
│   ├── evaluation_runner.py       # Resumable evaluation runner with multi-key failover
│   ├── compute_metrics.py         # Statistical evaluation engine
│   ├── audit_and_generate_artifacts.py # Generates results.csv and error_analysis.csv
│   ├── groq_client.py             # Robust Groq API wrapper with schema validation
│   ├── groq_config.py             # Secure configuration loader (zero key leaks)
│   ├── groq_key_manager.py        # Multi-key rotation and rate-limit tracking
│   ├── validate_dataset.py        # Dataset schema validation script
│   └── test_groq_system.py        # API health and multi-key rotation tests
├── outputs/
│   ├── evaluation_results.jsonl   # Raw evaluation log (900 completed jobs)
│   ├── results.csv                # Flattened tabular dataset with gold and predictions
│   ├── metrics_summary.json       # Summary dictionary of all verified metrics
│   └── final_metrics_reconciled.json # Comprehensive reconciled metrics
├── error_analysis/
│   ├── error_analysis.csv         # Detailed catalogue of all 272 audited failures
│   └── README.md                  # Error taxonomy, case studies, and mitigation guide
├── demo/
│   ├── demo_script.md             # 3-minute executive demo walkthrough & capture checklist
│   └── run_demo.py                # Interactive CLI demo showcasing key edge cases
└── report/
    ├── report_CS1.pdf             # Formatted 5-page publication-quality final report
    ├── generate_pdf_report.py     # Reproducible ReportLab PDF report builder
    ├── evaluation_report.md       # Full evaluation findings and confusion matrices
    └── dataset_audit.md           # Dataset construction and validation audit
```

---

## 3. Demo Evidence & Verification Walkthrough

The project provides an interactive demonstration script ([`demo/run_demo.py`](demo/run_demo.py)) and a step-by-step walkthrough ([`demo/demo_script.md`](demo/demo_script.md)) designed for a 3-minute presentation.

### Interactive Demonstration Scenarios:
1. **Scenario 1: The Rule A Door-Scratch Boundary (`TEST005`)**: Demonstrates how Zero-Shot and Few-Shot ($k=3, 5, 8$) anchor on "smashed quarter glass" and misclassify the claim as `glass_only`, whereas **Structured Reasoning** detects the scratched door panel and correctly outputs `own_damage`.
2. **Scenario 2: Roadway Feature vs Geographic Location (`TEST011`)**: Demonstrates that few-shot prompts hallucinate `"blind turn"` as the location, while **Structured Reasoning** recognizes it as a roadway feature and outputs `null`.
3. **Scenario 3: Third-Party Collision & Safety Triage (`TEST001`)**: Demonstrates 100.0% high-urgency triage recall when bodily injury or severe front-end damage occurs.

### Manual Screenshot Capture Checklist
For final submission evidence, genuine terminal screenshots can be captured directly from your environment using macOS Screenshot (`Cmd + Shift + 4`):

| Target Screenshot | Terminal Command / Source | Content to Capture |
|---|---|---|
| **01 — Input Message** | `head -n 5 data/test.jsonl` | Verbatim text of `TEST005` with vehicle reg, Bandra location, and door scratching. |
| **02 — Zero-Shot Output** | `python CS1_ClaimFast/demo/run_demo.py` | Strategy A output displaying JSON and `glass_only` misclassification. |
| **03 — Few-Shot Output** | `python CS1_ClaimFast/demo/run_demo.py` | Strategy B3 output displaying $k=8$ formatting and exemplar grounding. |
| **04 — Structured Reasoning Output** | `python CS1_ClaimFast/demo/run_demo.py` | Strategy C output displaying correct `own_damage` classification. |
| **05 — Strategy Comparison** | `python CS1_ClaimFast/demo/run_demo.py` | Comparison matrix showing side-by-side adjudication across all configurations. |
| **06 — Evaluation Results** | `python CS1_ClaimFast/code/compute_metrics.py` | Terminal output showing 900 jobs, 99.44% valid schema, and Macro-F1. |
| **07 — Error Analysis** | `head -n 25 error_analysis/error_analysis.csv` | Failure categories, root cause explanations, and proposed fixes. |
| **08 — Project Reproducibility** | `tree -L 2 CS1_ClaimFast/` | Verified directory tree and reproducible execution scripts. |

---

## 4. Benchmark Results & Key Findings

All metrics reflect the complete **900 evaluation jobs** ($N=180$ per strategy). Non-success jobs are penalized as zero-score mismatches across all fields:

| Prompt Strategy | Valid Schema Rate | Strict Match (All 9 Fields) | Normalized Match (Loc Norm) | `claim_type` Macro-F1 | `urgency` Macro-F1 | Mean Latency | Cost / 1k Claims |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **`zero_shot`** | 98.3% | 61.7% | 78.3% | 0.9851 | 0.9057 | 549.0 ms | $0.2709 |
| **`few_shot_k3`** | 99.4% | 64.4% | 81.1% | 0.9822 | **0.9305** | 545.9 ms | $0.3711 |
| **`few_shot_k5`** | **100.0%** | 71.7% | 80.0% | 0.9851 | 0.9143 | 563.7 ms | $0.4439 |
| **`few_shot_k8`** | 99.4%* | **86.1%** | **86.1%** | 0.9827 | 0.9283 | 668.9 ms | $0.5641 |
| **`structured_reasoning`** | **100.0%** | 65.0% | 81.7% | **0.9870** | 0.9143 | **510.0 ms** | **$0.3849** |
| **Benchmark Overall** | **99.4%** | **69.8%** | **81.4%** | **0.9844** | **0.9188** | **567.4 ms** | **$0.4070** |

*\*Note: `few_shot_k8` achieved 100% schema validity on executed calls; its 99.4% rate reflects 1 API token rate limit error.*

### Core Highlights
1. **Flawless Safety-Critical Triage**: Across all 240 high-urgency instances and 120 bodily injury instances, the model achieved **100.0% precision, 100.0% recall, and 1.0000 F1**. Zero injury or undrivable vehicle claims were missed.
2. **The Structured Reasoning Breakthrough**: Structured Reasoning was the **only strategy to correctly resolve the `TEST005` door-scratch edge case** under Rule A. It ran **23.8% faster** and cost **31.8% less** than $k=8$.
3. **Casing Normalization Impact**: 64.7% of all prediction mismatches were caused solely by casing differences in location extraction (e.g. `"mall basement"` vs `"Mall basement"`). Applying a lightweight title-casing normalizer raises benchmark exact match from 69.8% to **81.4%**.

---

## 5. Setup & Reproducibility Guide

### Step 1: Environment Setup
Ensure Python 3.11+ is installed. Clone the repository and install dependencies:
```bash
git clone https://github.com/VinitSurve/agentic_ai_case_studies.git
cd agentic_ai_case_studies

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r CS1_ClaimFast/requirements.txt
```

### Step 2: Configure API Credentials
Create a `.env` file in `CS1_ClaimFast/` (or root) based on `.env.example`:
```bash
cp CS1_ClaimFast/.env.example CS1_ClaimFast/.env
```
Add your Groq API key(s):
```ini
GROQ_API_KEY_1=gsk_your_primary_key_here
GROQ_API_KEY_2=gsk_your_backup_key_here  # Optional for failover
GROQ_MODEL=qwen/qwen3.8-27b
```

### Step 3: Run Interactive 3-Minute Demo
Experience the comparative performance across prompt strategies in 3 minutes:
```bash
python CS1_ClaimFast/demo/run_demo.py
```

### Step 4: Re-compute Metrics & Generate Artifacts
To verify all statistics from the raw `evaluation_results.jsonl` data:
```bash
python CS1_ClaimFast/code/compute_metrics.py
python CS1_ClaimFast/code/audit_and_generate_artifacts.py
```

### Step 5: Build Publication PDF Report
Rebuild the 5-page publication-quality PDF report:
```bash
python CS1_ClaimFast/report/generate_pdf_report.py
```
The output will be generated at `CS1_ClaimFast/report/report_CS1.pdf`.

---

## 6. Security & Secret Protection

- **Zero Key Leaks**: All raw API keys are sanitized in logging with `[REDACTED_key_X]`.
- **Git Hygiene**: `.env`, `.venv`, credentials, and local caches are strictly excluded via `.gitignore`.
