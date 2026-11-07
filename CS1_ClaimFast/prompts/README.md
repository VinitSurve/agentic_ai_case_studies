# ClaimFast – Prompt Engineering Experiment Setup (Phase 2)

This directory contains the standardized prompt templates designed for the **ClaimFast** motor insurance claim triage and entity extraction benchmark.

The goal of this phase is to establish controlled, reproducible prompt strategies to evaluate LLMs on unstructured, noisy, customer-submitted insurance messages in India.

---

## 1. Summary of Prompt Strategies

| Strategy | File | Examples ($k$) | Reasoning Mode | Primary Experimental Objective |
|---|---|:---:|---|---|
| **Strategy A** | `zero_shot.txt` | 0 | Direct extraction | Baseline capability of the model using detailed domain guidelines without in-context examples. |
| **Strategy B1** | `few_shot_k3.txt` | 3 | In-context demonstration | Effect of minimal demonstrative grounding ($k=3$) on JSON formatting, null mapping, and negative booleans. |
| **Strategy B2** | `few_shot_k5.txt` | 5 | In-context demonstration | Incremental gain of broader category coverage ($k=5$), adding component theft and municipal towing non-claims. |
| **Strategy B3** | `few_shot_k8.txt` | 8 | In-context demonstration | Full in-context coverage ($k=8$) encompassing all six claim types, confirmed total loss, hit-and-run, and Hinglish. |
| **Strategy C** | `structured_reasoning.txt` | 0 | Internal verification checklist | Effect of structured internal deliberation on edge-case adjudication and triage precision without exposing CoT. |

---

## 2. Shared Base Architecture

To ensure valid scientific comparison across strategies, **all five prompts share an identical base instruction core**:

1. **Claim Type Definitions**:
   - `own_damage`: Self-damage, single-vehicle collisions, weather, vandalism, and untraced hit-and-runs (Rule B).
   - `third_party_liability`: Actionable claims involving an identifiable responsible third party or damage caused to a third party.
   - `theft`: Entire vehicle or vehicle component theft (Rule A). Excludes theft of personal belongings.
   - `total_loss`: Officially declared/confirmed constructive total loss by surveyor or insurer (Rule C).
   - `glass_only`: Vehicle damage restricted exclusively to glass with zero body/mechanical damage (Rule A).
   - `not_a_claim`: Administrative inquiries, endorsements, NCB queries, towing for parking violations.

2. **Urgency Definitions**:
   - `high`: Any bodily injury reported (`injury_reported: true`) OR vehicle is undrivable / structurally unsafe.
   - `medium`: Claim requires operational attention without an immediate safety emergency.
   - `low`: Minor damage, cosmetic vandalism, drivable component loss, or non-urgent queries.

3. **Field Extraction Specifications**:
   - Exactly nine required output fields: `claim_type`, `urgency`, `policy_number`, `incident_date`, `location`, `vehicle_reg_no`, `estimated_amount_inr`, `injury_reported`, `police_report_filed`.
   - Internal metadata fields (`id`, `notes`) are strictly excluded from the output contract.

4. **Negative & Missing Information Constraints**:
   - Missing, relative, or uncertain information must be output as `null`.
   - Prohibition against guessing or inferring dates, locations, or vehicle registrations from external context.
   - Strict `false` standard: booleans can only be `false` when explicit negative evidence exists in the message.

---

## 3. Few-Shot Selection & Progression

All few-shot examples were selected **exclusively from the development dataset (`data/dev.jsonl`)**. Zero test records (`data/test.jsonl`) are present in any prompt, preserving the integrity of the held-out test split.

The few-shot examples follow a strict nested hierarchy: $k=3 \subset k=5 \subset k=8$.

### Inventory of Selected Examples

| Prompt | Example # | Source ID | Claim Type | Urgency | Key Learning Objective Demonstrated |
|---|:---:|:---:|---|---|---|
| **k=3, k=5, k=8** | Ex. 1 | `DEV001` | `third_party_liability` | `medium` | Third-party collision with identified responsible driver; integer INR conversion (`35000`); explicit `false` for injury; explicit `true` for police report; relative date mapped to `null`. |
| **k=3, k=5, k=8** | Ex. 2 | `DEV004` | `own_damage` | `high` | Suspected total loss (*"surveyor says it may be a total loss"*) remains `own_damage` per Rule C; `high` urgency due to undrivable burnt vehicle without injury; multiple unmentioned fields mapped to `null`. |
| **k=3, k=5, k=8** | Ex. 3 | `DEV006` | `glass_only` | `low` | Rule A: laptop bag stolen by breaking window is `glass_only` because vehicle damage is confined to glass; explicit `false` for police (*"have not gone to the police yet"*); low urgency. |
| **k=5, k=8** | Ex. 4 | `DEV013` | `theft` | `medium` | Vehicle component theft (battery and catalytic converter stolen) under Rule A; police diary entry filed; integer amount extraction. |
| **k=5, k=8** | Ex. 5 | `DEV010` | `not_a_claim` | `low` | Municipal corporation towing for parking violation is not theft; message requests advice rather than claim filing. |
| **k=8** | Ex. 6 | `DEV015` | `total_loss` | `high` | Surveyor officially declared constructive total loss per Rule C; unambiguous ISO calendar date extraction (`2026-07-28`); explicit `false` for both injury and police FIR. |
| **k=8** | Ex. 7 | `DEV009` | `own_damage` | `medium` | Untraced hit-and-run driver who fled is classified as `own_damage` per Rule B; explicit `false` for injury; unmentioned police status mapped to `null`. |
| **k=8** | Ex. 8 | `DEV011` | `third_party_liability` | `high` | Hinglish code-mixed phrasing; third-party bodily injury (*"auto driver ko chot aayi hai hospital le gaye"*) unconditionally requiring `urgency: high`; police FIR filed. |

---

## 4. Structured Reasoning Strategy Details

`structured_reasoning.txt` tests whether an explicit internal verification checklist improves model decision boundaries over direct zero-shot extraction.

### Core Differences from Zero-Shot:
- **Internal Checkpoints**: Introduces three verification checkpoints:
  1. *Classification Deliberation*: Explicit tests for Rule A (personal property vs component theft), Rule B (untraced hit-and-run vs identified third party), Rule C (suspected vs confirmed total loss), and administrative non-claims.
  2. *Urgency Calibration*: Enforces that bodily injuries mandate `high` urgency, undrivable damage mandates `high`, and minor/drivable damage is calibrated to `low` or `medium`.
  3. *Entity & Null Verification*: Pre-flight checks on ISO date formatting, uppercase registration formatting, and strict negative boolean confirmation.
- **Output Constraint**: Strict requirement that private chain-of-thought, reasoning steps, or notes must **not** be exposed in the output. The model must emit only the final raw JSON object.

---

## 5. Experimental Hypotheses for Phase 3 Evaluation

When evaluating these prompts against the 60 held-out test records in Phase 3, we will test:
1. **In-Context Grounding vs. Hallucination**:
   - *Hypothesis*: Few-shot prompts ($k=3, 5, 8$) will significantly outperform zero-shot on mapping relative dates ("yesterday") to `null` instead of generating arbitrary calendar dates.
2. **Impact of Scaling $k$ on Boundary Disambiguation**:
   - *Hypothesis*: $k=8$ will show superior performance on untraced hit-and-run (`TEST020`), suspected total loss (`TEST004`), and Hinglish transliterations (`TEST002`, `TEST040`, `TEST045`) due to direct exemplar alignment.
3. **Structured Reasoning vs. Few-Shot Efficiency**:
   - *Hypothesis*: Structured reasoning will achieve higher triage urgency accuracy ($F_1$) without incurring the token latency and prompt context cost of few-shot demonstrations.

---

## 6. Experimental Limitations: Category Coverage vs. Sample Size ($k$)

An important methodological limitation in the experimental design of the nested few-shot prompts ($k=3, 5, 8$) is the **confounding relationship between example count and claim-category coverage**:

- **$k=3$ (3 of 6 categories covered - 50.0%)**:
  - Demonstrates: `third_party_liability` (`DEV001`), `own_damage` (`DEV004`), `glass_only` (`DEV006`).
  - Unrepresented categories: `theft`, `total_loss`, `not_a_claim`.
- **$k=5$ (5 of 6 categories covered - 83.3%)**:
  - Adds: `theft` (`DEV013`), `not_a_claim` (`DEV010`).
  - Unrepresented category: `total_loss`.
- **$k=8$ (6 of 6 categories covered - 100.0%)**:
  - Adds: `total_loss` (`DEV015`), along with reinforcing edge cases for `own_damage` (`DEV009`, untraced hit-and-run) and `third_party_liability` (`DEV011`, Hinglish injury).
  - Represents all 6 of 6 claim categories in the taxonomy.

### Confounding Factor Analysis
Because the nested prompt hierarchy introduces previously unseen claim categories at each scale step, **performance improvements across $k$ cannot be attributed exclusively to the number of in-context examples**.

Any observed accuracy gains reflect a dual effect:
1. **Quantitative Scaling**: The sheer number of few-shot demonstrations provided in context ($k=3 \rightarrow 5 \rightarrow 8$).
2. **Taxonomic Discovery**: Qualitative category discovery as the model receives direct in-context definitions and demonstration targets for missing classes (e.g., encountering constructive total loss or parking towing non-claims for the first time).


