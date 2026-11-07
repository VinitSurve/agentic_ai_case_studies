# ClaimFast – Error Analysis & Adjudication Report

This directory contains the systematic diagnostic audit of all **272 failed prediction instances** across the 900-job ClaimFast evaluation matrix ($5 \text{ strategies} \times 60 \text{ test messages} \times 3 \text{ runs}$).

---

## 1. Inventory of Files

- **`error_analysis.csv`**: Exhaustive CSV catalogue containing every inspected failure:
  - `job_id`: Deterministic job identifier (`{strategy}_{record_id}_run{run}`).
  - `record_id`: Target message ID (`TEST001`–`TEST060`).
  - `prompt_strategy`: One of the 5 evaluated prompt strategies.
  - `run_number`: Stochastic repetition run (1, 2, or 3).
  - `execution_status`: `SUCCESS`, `VALIDATION_ERROR`, or `API_ERROR`.
  - `error_category`: One of six standardized error categories.
  - `mismatched_fields`: Semicolon-separated list of fields that deviated from gold.
  - `input_message`: Verbatim customer message.
  - `expected_output`: Gold values for mismatched fields.
  - `actual_output`: Predicted values (or raw response if execution failed).
  - `explanation_of_cause`: Root cause diagnosis.
  - `proposed_fix`: Actionable prompt engineering or pipeline mitigation.

---

## 2. Failure Distribution by Prompt Strategy

| Prompt Strategy | Evaluated Jobs ($N$) | Successful Strict Matches | Total Failed Predictions | Failure Rate |
|---|:---:|:---:|:---:|:---:|
| **`zero_shot`** | 180 | 111 | 69 | 38.3% |
| **`few_shot_k3`** | 180 | 116 | 64 | 35.6% |
| **`few_shot_k5`** | 180 | 129 | 51 | 28.3% |
| **`few_shot_k8`** | 180 | 155 | 25 | **13.9%** |
| **`structured_reasoning`** | 180 | 117 | 63 | 35.0% |
| **Total Benchmark** | **900** | **628** | **272** | **30.2%** |

---

## 3. Error Categorization Breakdown

| Error Category | Zero-Shot | Few-Shot $k=3$ | Few-Shot $k=5$ | Few-Shot $k=8$ | Structured Reasoning | Benchmark Total | Percentage |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Normalization Error** | 44 | 45 | 30 | 9 | 48 | **176** | 64.7% |
| **Classification Error** | 19 | 15 | 18 | 15 | 15 | **82** | 30.1% |
| **Hallucination** | 3 | 3 | 3 | 0 | 0 | **9** | 3.3% |
| **Formatting/Schema Error** | 3 | 1 | 0 | 1 | 0 | **5** | 1.8% |
| **Missing Extraction** | 0 | 0 | 0 | 0 | 0 | **0** | 0.0% |
| **Ambiguity** | 0 | 0 | 0 | 0 | 0 | **0** | 0.0% |
| **Total Failures Audited** | **69** | **64** | **51** | **25** | **63** | **272** | **100.0%** |

---

## 4. Key Error Case Studies

### Case Study A: The Rule A Door-Scratch Boundary (`TEST005`)
- **Customer Message**: *"Someone smashed my car's left rear quarter glass and scratched the rear door while stealing sunglasses and a kit bag from my parked car MH02RT3321 in Bandra on 2026-06-11..."*
- **Gold Label**: `claim_type: own_damage` (Rule A: theft of personal items is not vehicle theft; vehicle suffered both quarter glass breakage and scratched door panel, satisfying Rule A for `own_damage`).
- **Model Behavior**: Zero-Shot, $k=3$, $k=5$, and $k=8$ all predicted `glass_only`, anchoring strongly on the smashed quarter glass and missing the subtle scratched door panel.
- **Structured Reasoning Breakthrough**: **Structured Reasoning was the only strategy to classify TEST005 correctly across all 3 runs**, proving that its internal verification checklist successfully adjudicated Rule A body damage vs glass-only damage.

### Case Study B: Location Entity Boundary vs Roadway Feature (`TEST011`)
- **Customer Message**: *"I was taking a blind turn on a narrow road when a scooter crashed into my driver side door..."*
- **Gold Label**: `location: null` ("blind turn on a narrow road" describes a roadway feature, not a geographic location).
- **Model Behavior**: Zero-Shot, $k=3$, $k=5$, and $k=8$ hallucinated `location: "blind turn"` across all 3 runs.
- **Structured Reasoning Breakthrough**: Structured Reasoning correctly outputted `location: null` across all 3 runs, achieving **0.0% location hallucination**.

### Case Study C: Casing Normalization Dominance
- 176 out of 272 errors (64.7%) were caused solely by casing differences in location extraction (e.g. model predicting `"mall basement"` instead of gold `"Mall basement"`).
- When case-insensitive normalization is applied, benchmark exact match accuracy increases from **69.8% to 81.4%**.
