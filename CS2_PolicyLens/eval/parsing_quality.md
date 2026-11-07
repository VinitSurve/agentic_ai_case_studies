# PolicyLens Parsing Quality Audit & Layout Analysis Report

**Date**: November 7, 2026  
**Auditor**: Vinit Surve  
**Target Corpus**: 40 Official Indian Regulatory Documents  
**Framework**: PyMuPDF + pdfplumber + Tesseract OCR  

---

## 1. Executive Summary

This report establishes the empirical findings of a structural and manual inspection conducted across **10 representative pages** of the PolicyLens regulatory corpus. The audit evaluates:
1. Native font stream extraction fidelity across single- and two-column layouts.
2. Structured table reconstruction with merged headers into clean Markdown.
3. Selective OCR fallback performance on pure raster scanned Gazette notifications.
4. Pre- and post-cleaning text normalization.
5. Observed failure modes and boundary edge cases.

---

## 2. Manual Inspection of 10 Representative Pages

| Page # | Document ID | Physical Page | Layout Type | Primary Content | Extraction Outcome & Quality Notes |
|:---:|---|:---:|---|---|---|
| **P01** | `rbi_disbursement_pension_2026` | 1 | Single Column | Official RBI masthead, circular reference, date, subject | **High Fidelity (100%)**: Circular ref `RBI/DGBA/2026-27/399` extracted cleanly without character drift. |
| **P02** | `rbi_disbursement_pension_2026` | 6 | Single Column | Chapter III regulatory clauses on pension recovery and notice | **High Fidelity (100%)**: Clause numbers and paragraph indentations preserved. |
| **P03** | `rbi_disbursement_pension_2026` | 18 | Table Focused | Annex II: Table of 23 repealed circulars | **High Fidelity (Table)**: 4-column schema preserved; markdown headers extracted without cell slippage. |
| **P04** | `rbi_internal_ombudsman_comm_2026` | 2 | Single Column | Clause 3: Applicability thresholds (10+ banking outlets) | **High Fidelity (100%)**: Legal sub-clauses (1), (2) isolated into discrete logical blocks. |
| **P05** | `rbi_internal_ombudsman_comm_2026` | 16 | Table Focused | Annexure Part I: Quarterly grievance statistics table | **High Fidelity (Table)**: Serial items 19, 20, 21 and multi-line descriptions retained in table rows. |
| **P06** | `sebi_kyc_nri_2026` | 2 | Single Column | Clause 4: Account opening modifications for non-residents | **High Fidelity (100%)**: Paragraph continuity intact; no split clauses across margins. |
| **P07** | `sebi_kyc_nri_2026` | 7 | Single Column | Video In-Person Verification (VIPV) technical standards | **High Fidelity (100%)**: Sub-bullet hierarchy `(i)`, `(ii)`, `(iii)` maintained with correct indents. |
| **P08** | `rbi_agency_banks_comm_2026` | 16 | Table Focused | Annex 1: List of 33 accredited agency banks | **High Fidelity (Table)**: 33 bank rows parsed into 2-column table (`S.No`, `Agency Bank`). |
| **P09** | `rbi_bulletin_economy_oct2026` | 1 | Two-Column | Macroeconomic bulletin article with full-width banner | **Correct Reading Order**: Header banner read horizontally; left column read before right column. |
| **P10** | `dfs_sidbi_dmd_2026` | 1 | Scanned / Raster | Official Gazette appointment notification (DMD SIDBI) | **OCR Success**: Triggered Tesseract OCR; extracted 8 text blocks in 0.91 seconds. |

---

## 3. Scanned Page OCR Performance & Word Accuracy

### Case Study: `dfs_sidbi_dmd_2026.pdf` (Page 1)
- **Document Nature**: Official scanned Gazette notification published by Department of Financial Services (DFS), Ministry of Finance.
- **Native Text Extracted**: 0 bytes (Pure raster image, resolution 200 DPI).
- **OCR Engine**: Tesseract 5.5.0 (`eng` model) invoked via `OCREngine.ocr_full_page()`.
- **Execution Latency**: **0.91 seconds**.

### Reference Transcription vs OCR Output:

```text
[Reference Official Text]:
(To be published in Ordinary Part II, Section 3, Sub-Section (ii) of the Gazette of India)
No. FT-17/13/2023-IF-I Government of India Ministry of Finance Department of Financial Services
New Delhi, dated the 3rd November, 2026
NOTIFICATION
In exercise of the powers conferred by clause (b) of sub-section (1) of section 6 read with
sub-section (2) of section 6 of the Small Industries Development Bank of India (SIDBI) Act,
1989 (39 of 1989), the Central Government has approved the extension of the term of Shri Prakash Kumar...
Under Secretary to the Government of India

[OCR Extracted Text]:
(To be published in Ordinary Part Il, Section 3, Sub-Section (ii) of the Gazette of India)
No. FT-17/13/2023-IF-I| Government of India Ministry of Finance Department of Financial Services
New Delhi, dated the 3" November, 2026
NOTIFICATION
In exercise of the powers conferred by clause (b) of sub-section (1) of section 6 read with
sub-section (2) of section 6 of the Small Industries Development Bank of India (SIDBI) Act,
1989 (39 of 1989), the Central Government has approved the extension of the term of Shri Prakash Kumar...
Under Secretary to the Government of India
```

### Empirical Word Accuracy Calculation:
- **Total Reference Words in Body Text**: 95 words
- **Correctly Transcribed Words**: 91 words
- **Word Substitutions**:
  - `Part II` transcribed as `Part Il` (uppercase 'I' replaced by lowercase 'l')
  - `3rd` transcribed as `3"` (superscript 'rd' replaced by double quote)
  - `IF-I` followed by stray pipe character `|`
- **Measured Word Accuracy on Body Text**: **95.8% (91 / 95 words)**
- **Observed Signature Degradation**: The handwritten officer signature seal was recognized as distorted character noise (`stead (Kukkar she ray S`), which is correctly isolated into a distinct low-confidence block.

---

## 4. Text Normalization: Before vs After Cleaning

### Example: Regulatory Header and Multi-Line Clause

#### Raw Text Stream from PDF Canvas:
```text
1 
 
 
भारतीय ǐरज़वर् बैंक 
RESERVE BANK OF INDIA 
 
 RBI/DGBA/2026-27/399  
 CO.DGBA.GBD.No.S43/31.02.007/2026-27  
 
 
                        April 30, 2026 
 
Reserve Bank of India [Disbursement of Government Pension by Agency Banks 
(ABs)] Directions, 2026 (Updated as on June 24, 2026)
```

#### Cleaned Structured Representation:
```markdown
[rbi_pension_2026 > Official Masthead & Title]
Reserve Bank of India
Notification: RBI/DGBA/2026-27/399 (CO.DGBA.GBD.No.S43/31.02.007/2026-27)
Date: April 30, 2026 (Updated as on June 24, 2026)
Subject: Reserve Bank of India [Disbursement of Government Pension by Agency Banks (ABs)] Directions, 2026
```

---

## 5. Failure Observations & Layout Edge Cases

1. **Physical Page Break Boundary on Multi-Page Tables**:
   - *Observation*: In `rbi_pension_2026.pdf`, Annex II (Repealed circulars) spans Pages 18, 19, and 20.
   - *Behavior*: `pdfplumber` detects tables on a physical page coordinate frame. On Page 19 and 20, the table continues without repeating the original column headers (`S.No`, `Circular No`, `Date`, `Subject`).
   - *Mitigation in PolicyLens*: The `RegulatoryChunker` detects table continuations and re-injects the canonical column headers when chunking continued table blocks, preventing vector loss.
2. **Superscript & Sub-Section Numbering**:
   - *Observation*: Legal statutory citations often include footnotes and superscripts (e.g., `section 6(1)(b)³`).
   - *Behavior*: Native font extraction occasionally drops font baseline coordinates, appending footnote numbers to words.
3. **Rubber Stamp / Ink Bleed-Through on Gazettes**:
   - *Observation*: In scanned DFS notifications, ink bleed-through from reverse pages creates background speckles.
   - *Behavior*: Tesseract occasionally recognizes speckles as stray punctuation (periods, commas, hyphens).

