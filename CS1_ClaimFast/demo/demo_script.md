# ClaimFast – 3-Minute Interactive Demo Walkthrough

This document outlines a self-contained, 3-minute executive and technical demonstration of the **ClaimFast** motor insurance triage and entity extraction benchmark.

---

## 1. Demo Objectives
In under three minutes, demonstrate:
1. The challenges of unstructured, code-mixed, and ambiguous customer FNOL communications.
2. How different prompt configurations (`zero_shot`, `few_shot_k3`, `few_shot_k5`, `few_shot_k8`, `structured_reasoning`) process the identical noisy input message.
3. Why **Structured Reasoning** and **Few-Shot k=8** outperform baseline zero-shot extraction on edge-case adjudication and schema reliability.

---

## 2. Interactive CLI Demo Script

A self-contained runnable demo script is provided at [`CS1_ClaimFast/demo/run_demo.py`](file:///Users/vinit/Vinit/ITM/Agent AI Foundations/LLM_Case_Studies/CS1_ClaimFast/demo/run_demo.py).

### How to Run:
```bash
cd "/Users/vinit/Vinit/ITM/Agent AI Foundations/LLM_Case_Studies/CS1_ClaimFast"
../.venv/bin/python demo/run_demo.py
```

### Demonstration Scenarios Tested in the Demo:
- **Scenario 1 (`TEST005` - The Rule A Personal Theft & Body Damage Boundary)**:
  - *Message*: *"Someone smashed my car's left rear quarter glass and scratched the rear door while stealing sunglasses and a kit bag from my parked car MH02RT3321 in Bandra on 2026-06-11. Did not go to police. Estimated repair 9500 rs. Policy PL-9098."*
  - *Demonstration Point*: Zero-Shot, k=3, k=5, and k=8 anchor on "smashed quarter glass" and misclassify as `glass_only`. Only **Structured Reasoning** catches the scratched door panel and correctly classifies as `own_damage`.
- **Scenario 2 (`TEST011` - Feature vs. Location Hallucination)**:
  - *Message*: *"I was taking a blind turn on a narrow road when a scooter crashed into my driver side door..."*
  - *Demonstration Point*: Few-shot prompts hallucinate `"blind turn"` as the location. **Structured Reasoning** recognizes this is a roadway feature and correctly extracts `null`.
- **Scenario 3 (`DEV001` - Third-Party Fault & Integer Conversion)**:
  - *Message*: *"An auto rickshaw rear-ended my Swift at Silk Board signal yesterday. The driver admitted fault and gave his DL details. Workshop estimated 35k for rear bumper and boot lid. Filed an entry at Madiwala traffic PS. Nobody was injured. Policy POL-789012."*
  - *Demonstration Point*: Demonstrates relative date ("yesterday") mapping to `null`, integer INR conversion (`35000`), explicit negative injury (`false`), and actionable third-party liability classification.

---

## 3. Minute-by-Minute Presentation Script

### Minute 1: The Problem & Baseline Zero-Shot Extraction
> *"Welcome. In Indian motor insurance, customer FNOL messages arrive via WhatsApp, webchat, or email. They are unstructured, code-mixed, and full of complex edge cases.
> Let's look at Scenario 1: A customer reports that someone broke their car's quarter glass and scratched the door while stealing sunglasses.
> In auto insurance, personal belongings theft is excluded from auto coverage. If only glass is broken, it's `glass_only`. But here, the door panel was also scratched.
> When we run baseline Zero-Shot, the model anchors on 'smashed quarter glass' and misclassifies the claim as `glass_only`. It also suffers occasional key hallucinations like `injury_reporting` instead of `injury_reported`."*

### Minute 2: Few-Shot In-Context Grounding
> *"Now let's examine Few-Shot demonstration from k=3 to k=8.
> Adding in-context examples completely eliminates schema validation errors and grounds the model on exact verbatim spans. Location strict accuracy jumps from 73% in Zero-Shot to 92.8% in k=8!
> However, k=8 comes with tradeoffs: it triples prompt token usage (2,712 tokens) and increases latency by 22%. Furthermore, all few-shot prompts still missed the door scratch in Scenario 1."*

### Minute 3: The Structured Reasoning Breakthrough & Recommendation
> *"Finally, we introduce Structured Reasoning.
> Instead of few-shot examples, Structured Reasoning provides an internal deliberative verification checklist that checks Rule A, Rule B, and Rule C before emitting the final JSON.
> Structured Reasoning is the only strategy to correctly classify Scenario 1 as `own_damage`. It eliminates location hallucinations, achieves 100% schema validity, and executes in just 510 milliseconds—24% faster than k=8.
> Our production recommendation: Deploy Structured Reasoning with a lightweight casing normalizer for maximum accuracy at minimal token cost."*
