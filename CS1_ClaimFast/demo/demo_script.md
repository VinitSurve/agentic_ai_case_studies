# ClaimFast – 3-Minute Interactive Demo Walkthrough

This document outlines a self-contained, 3-minute executive and technical demonstration of the **ClaimFast** motor insurance claim triage and entity extraction benchmark, designed for live presentation and screenshot capture.

---

## 1. Demo Objectives
In under three minutes, demonstrate:
1. The challenges of unstructured, code-mixed, and ambiguous customer FNOL communications.
2. How different prompt configurations (`zero_shot`, `few_shot_k3`, `few_shot_k5`, `few_shot_k8`, `structured_reasoning`) process the identical noisy input message.
3. Why **Structured Reasoning** and **Few-Shot k=8** outperform baseline zero-shot extraction on edge-case adjudication and schema reliability.

---

## 2. Interactive CLI Demo Script

A self-contained runnable demo script is provided at [`CS1_ClaimFast/demo/run_demo.py`](run_demo.py).

### How to Run:
```bash
cd "/Users/vinit/Vinit/ITM/Agent AI Foundations/LLM_Case_Studies"
python CS1_ClaimFast/demo/run_demo.py
```

---

## 3. Minute-by-Minute Presentation Script & Capture Points

### Minute 1: The Problem & Baseline Zero-Shot Extraction

#### Capture Point 1: Customer Input Message (`TEST005`)
- **Input Text**:
  > *"Someone smashed my car's left rear quarter glass and scratched the rear door while stealing sunglasses and a kit bag from my parked car MH02RT3321 in Bandra on 2026-06-11. Did not go to police. Estimated repair 9500 rs. Policy PL-9098."*
- **Presentation Script**:
  > *"Welcome. In Indian motor insurance, customer FNOL messages arrive via WhatsApp, webchat, or email. They are unstructured, code-mixed, and full of complex edge cases.*
  > *Let's look at Scenario 1 (TEST005): A customer reports that someone broke their car's quarter glass and scratched the door while stealing sunglasses in Bandra on 2026-06-11.*
  > *In auto insurance under Rule A: theft of personal belongings is excluded from vehicle theft coverage. If only glass is broken, it's `glass_only`. But here, the door panel was also scratched, which constitutes automotive body damage, making it `own_damage`."*

#### Capture Point 2: Zero-Shot Baseline Output
- **Model Output**:
  ```json
  {
    "claim_type": "glass_only",
    "urgency": "low",
    "policy_number": "PL-9098",
    "incident_date": "2026-06-11",
    "location": "Bandra",
    "vehicle_reg_no": "MH02RT3321",
    "estimated_amount_inr": 9500,
    "injury_reported": null,
    "police_report_filed": false
  }
  ```
- **Presentation Script**:
  > *"When we run baseline Zero-Shot (Strategy A), the model successfully extracts all nine required fields into valid JSON, including the ISO date `2026-06-11`, policy `PL-9098`, and integer amount `9500`.*
  > *However, it misclassifies the claim as `glass_only`! The model anchored strongly on 'smashed quarter glass' and failed to recognize that the scratched door panel requires `own_damage` triage. Furthermore, across the full zero-shot benchmark, we observed morphological schema errors like `injury_reporting` instead of `injury_reported`."*

---

### Minute 2: Few-Shot In-Context Grounding

#### Capture Point 3: Few-Shot Grounded Output ($k=8$)
- **Model Output**:
  ```json
  {
    "claim_type": "glass_only",
    "urgency": "low",
    "policy_number": "PL-9098",
    "incident_date": "2026-06-11",
    "location": "Bandra",
    "vehicle_reg_no": "MH02RT3321",
    "estimated_amount_inr": 9500,
    "injury_reported": null,
    "police_report_filed": false
  }
  ```
- **Presentation Script**:
  > *"Now let's examine Few-Shot demonstration scaling to k=8 (Strategy B3).*
  > *In-context grounding provides immediate structural benefits: schema validation errors drop to zero on completed executions, and strict location extraction accuracy jumps from 73.3% to 92.8% because the exemplars teach the model to preserve exact text spans and proper noun casing.*
  > *However, k=8 comes with trade-offs: prompt token footprint triples to 2,712 tokens, increasing latency by 22% (668.9ms) and cost to $0.56 per 1,000 claims. More importantly, exemplar DEV006 demonstrated personal laptop theft with window breakage, causing k=8 to overfit and still misclassify TEST005 as `glass_only`."*

---

### Minute 3: The Structured Reasoning Breakthrough & Strategic Verdict

#### Capture Point 4: Structured Reasoning Deliberation
- **Checkpoints**:
  - `[✓] Checkpoint 1 (Rule A Verification)`: Scratched door panel detected $\rightarrow$ Body damage exists $\rightarrow$ `claim_type: "own_damage"`.
  - `[✓] Checkpoint 2 (Urgency Calibration)`: No physical injury, drivable vehicle $\rightarrow$ `urgency: "low"`.
  - `[✓] Checkpoint 3 (Entity & Negative Boolean Audit)`: Explicit negative for police $\rightarrow$ `false`; injury unstated $\rightarrow$ `null`.
- **Final Permitted Output**:
  ```json
  {
    "claim_type": "own_damage",
    "urgency": "low",
    "policy_number": "PL-9098",
    "incident_date": "2026-06-11",
    "location": "Bandra",
    "vehicle_reg_no": "MH02RT3321",
    "estimated_amount_inr": 9500,
    "injury_reported": null,
    "police_report_filed": false
  }
  ```
- **Presentation Script**:
  > *"Finally, we introduce Structured Reasoning (Strategy C).*
  > *Instead of few-shot examples, Structured Reasoning enforces an internal cognitive verification checklist before emitting the final JSON: Checkpoint 1 adjudicates Rule A body damage vs glass-only; Checkpoint 2 calibrates urgency; Checkpoint 3 audits negative booleans.*
  > *As you can see, Structured Reasoning is the ONLY strategy that correctly classifies TEST005 as `own_damage`! It suppresses private chain-of-thought and emits strictly conformant JSON.*
  > *Best of all: it runs in just 510.0 milliseconds—23.8% faster than k=8—and consumes 31.8% fewer tokens ($0.38 per 1k claims)."*

#### Capture Point 5: Cross-Strategy Adjudication Comparison
- **Presentation Script**:
  > *"Here is the side-by-side comparison across all prompt configurations on TEST005 and TEST011:*
  > *Notice that for TEST005, only Structured Reasoning achieved a 9/9 strict match. In TEST011, where an input mentioned a 'blind turn on a narrow road', all few-shot prompts hallucinated 'blind turn' as the location, whereas Structured Reasoning correctly recognized it as a roadway feature and outputted `null`.*
  > *And across all strategies, high-urgency triage achieved a flawless 100% recall with zero safety escapes."*

---

## 4. Benchmark & Diagnostic Evidence

#### Capture Point 6: Final Benchmark Evaluation Results (900 Jobs)
- Command: `python CS1_ClaimFast/code/compute_metrics.py`
- Evidence: 900 / 900 jobs completed, 99.44% valid schema, 0.9844 Macro-F1, 100.0% safety recall (240 / 240).

#### Capture Point 7: Diagnostic Error Categorization (272 Failures)
- Source: `CS1_ClaimFast/error_analysis/error_analysis.csv`
- Evidence: 176 normalization casing differences (64.7%), 82 classification calibrations (30.1%), 9 hallucinations (3.3%), 5 schema errors (1.8%).

#### Capture Point 8: Project Architecture & Reproducibility
- Command: `tree -L 2 CS1_ClaimFast/`
- Evidence: Verifiable directory structure, publication PDF report (`report_CS1.pdf`), and flattened dataset (`results.csv`).

---

## 5. Visual Evidence Repository (`screenshots/ClaimFast_12_Screenshots/`)

All 12 genuine presentation screenshots are cataloged and tracked in [`CS1_ClaimFast/demo/screenshots/ClaimFast_12_Screenshots/`](screenshots/ClaimFast_12_Screenshots):
- [`01_project_location.png`](screenshots/ClaimFast_12_Screenshots/01_project_location.png): Project location and execution root
- [`02_project_folder_structure.png`](screenshots/ClaimFast_12_Screenshots/02_project_folder_structure.png): File hierarchy and directory tree
- [`03_dataset_split_and_sample_records.png`](screenshots/ClaimFast_12_Screenshots/03_dataset_split_and_sample_records.png): Dev and test JSONL dataset inspection
- [`04_prompt_templates.png`](screenshots/ClaimFast_12_Screenshots/04_prompt_templates.png): Prompt configuration templates
- [`05_evaluation_run_status.png`](screenshots/ClaimFast_12_Screenshots/05_evaluation_run_status.png): Complete 900-job batch evaluation run status
- [`06_detailed_evaluation_output.png`](screenshots/ClaimFast_12_Screenshots/06_detailed_evaluation_output.png): Raw generation logs and schema validation
- [`07_evaluation_analysis_part_1.png`](screenshots/ClaimFast_12_Screenshots/07_evaluation_analysis_part_1.png): Benchmark metrics (Schema validity & field accuracy)
- [`08_evaluation_analysis_part_2.png`](screenshots/ClaimFast_12_Screenshots/08_evaluation_analysis_part_2.png): Classification Macro-F1 and safety triage
- [`09_evaluation_analysis_part_3.png`](screenshots/ClaimFast_12_Screenshots/09_evaluation_analysis_part_3.png): Strategy latency and cost benchmarking
- [`10_error_analysis_csv_preview.png`](screenshots/ClaimFast_12_Screenshots/10_error_analysis_csv_preview.png): Tabular error taxonomy preview
- [`11_report_benchmark_and_safety_tables.png`](screenshots/ClaimFast_12_Screenshots/11_report_benchmark_and_safety_tables.png): ReportLab final executive report benchmark tables
- [`12_report_error_analysis_and_consistency.png`](screenshots/ClaimFast_12_Screenshots/12_report_error_analysis_and_consistency.png): ReportLab final executive report error analysis and run consistency
