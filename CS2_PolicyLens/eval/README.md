# PolicyLens Evaluation Benchmark: Structure-Aware vs Fixed-Window Retrieval

This directory contains the reproducible retrieval evaluation suite for PolicyLens (Case Study 2).

---

## 1. Evaluation Methodology

- **Evaluation Dataset**: 25 realistic, expert-audited compliance questions based on the active indexed regulatory corpus (`eval/questions.csv`).
  - **Question Composition**:
    - Standard text clause questions: 14 questions
    - Table-lookup questions (fee matrices, repealed circular lists, accredited bank lists): 6 questions
    - Paraphrased/semantic questions (divergent terminology from source): 5 questions
  - **Gold Ground Truth**: Verified against physical PDF page numbers and source excerpts; zero fabricated labels.
- **Controlled Comparison**:
  - Embedding Engine: `sentence-transformers/all-MiniLM-L6-v2` (384-dim, normalized, CPU-executed) kept constant.
  - Evaluation Questions: Kept constant.
  - Parsing Pipeline: Identical `ParsedDocument` representation fed to both chunkers.
  - **Strategy A**: `policylens_structure` (Structure-aware, ~350 body tokens, hierarchical breadcrumbs `[Document > Heading]`, Markdown table preservation).
  - **Strategy B**: `policylens_fixed` (Fixed-size sliding window, 500 tokens, 50 token overlap).
- **Hit Definition**: A retrieved chunk is deemed a hit if its `document_id` matches the gold document and its page number overlaps the gold page ($\pm 1$ page boundary tolerance for multi-page clauses) or contains the gold evidence excerpt.

---

## 2. Empirical Benchmark Results (25 Questions)

| Evaluation Metric | Structure-Aware Chunking | Fixed-Window Baseline (500/50) | Absolute Improvement |
|---|:---:|:---:|:---:|
| **Recall@3** | **96.0%** (24 / 25) | 92.0% (23 / 25) | **+4.0%** |
| **Recall@5** | **100.0%** (25 / 25) | 100.0% (25 / 25) | Parity |
| **Recall@10** | **100.0%** (25 / 25) | 100.0% (25 / 25) | Parity |
| **Mean Reciprocal Rank (MRR)** | **0.9100** | 0.8333 | **+0.0767 (+9.2%)** |

### Key Findings:
1. **Higher Precision at Top Ranks (MRR +9.2%)**: Structure-aware chunking places the correct regulatory clause at Rank 1 significantly more often than fixed-size chunking. Breadcrumb headers (`[rbi_pension_2026 > Annex II - Repealed Circulars]`) ground the semantic search vector directly in the section topic.
2. **Table Schema Integrity**: In table-lookup questions (e.g., `Q06`), structure-aware chunking keeps table headers and row cells aligned in clean Markdown, achieving Rank 1 retrieval, whereas fixed-size slicing splits table headers across chunk boundaries, degrading retrieval to Rank 4.

---

## 3. Disagreement Case Studies

The two strategies disagreed on top-3 retrieval in exactly 3 instances:

### Case 1: `Q06` — Repealed Circular Table Lookup (`table_lookup`)
- **Question**: *"What is the circular reference number of the repealed instruction dated 14.10.2009 for pension withdrawal facilities through public sector banks?"*
- **Gold Target**: `rbi_pension_2026`, Page 19 (Annex II Table)
- **Structure-Aware Rank**: **Rank 1** (Score: 0.658) — Correct table chunk retrieved first.
- **Fixed-Window Rank**: **Rank 4** (Score: 0.542) — Window boundary severed the table header from row 9.
- **Winner**: **Structure-Aware Advantage**

### Case 2: `Q10` — Minimum Outlets Applicability (`text_standard`)
- **Question**: *"What is the minimum threshold of banking outlets for a commercial bank to fall under the mandatory Internal Ombudsman framework?"*
- **Gold Target**: `rbi_io_comm_2026`, Page 2 (Clause 3: Applicability)
- **Structure-Aware Rank**: **Rank 1** (Score: 0.691) — Clause 3 retained as a discrete legal unit.
- **Fixed-Window Rank**: **Rank 4** (Score: 0.563) — Padded with generic preamble, diluting vector similarity.
- **Winner**: **Structure-Aware Advantage**

### Case 3: `Q23` — Agency Bank List Annex 1 (`table_lookup`)
- **Question**: *"In Annex 1 of the agency bank directions, which agency bank is listed under serial number 2?"*
- **Gold Target**: `rbi_agency_comm_2026`, Page 16 (Annex 1 Table)
- **Structure-Aware Rank**: **Rank 4** (Score: 0.584) — Sliced table section into multiple sub-blocks.
- **Fixed-Window Rank**: **Rank 2** (Score: 0.627) — Large 500-token window captured rows 1 to 20 continuously.
- **Winner**: **Fixed-Window Advantage**

---

## 4. How to Reproduce

Run the automated evaluation runner:
```bash
python CS2_PolicyLens/eval/run_retrieval_eval.py
```
Outputs are automatically written to:
- `eval/retrieval_results.csv` (Per-question ranks and top-1 predictions)
- `eval/metrics.json` (Machine-readable summary metrics)

