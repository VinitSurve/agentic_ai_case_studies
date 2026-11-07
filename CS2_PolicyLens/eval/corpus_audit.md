# PolicyLens Corpus Audit Summary

**Date**: November 7, 2026  
**Corpus Root**: `CS2_PolicyLens/data/pdfs/`  
**Manifest Path**: `CS2_PolicyLens/data/manifest.csv`  

---

## 1. Executive Summary

A comprehensive structural audit was conducted across the 40 official regulatory PDF documents comprising the PolicyLens corpus. All 40 files exist on disk, are valid PDF specifications, and match their recorded SHA-256 integrity hashes in the manifest.

| Metric | Measured Value | Verification Details |
|---|:---:|---|
| **Total Regulatory Documents** | **40 PDFs** | 100% present in `data/pdfs/` |
| **Total Corpus Page Count** | **1,123 Pages** | Exact physical page count extracted via PyMuPDF |
| **Total Disk Size** | **30.75 MB** | 32,243,712 bytes across all PDF assets |
| **Missing Metadata Fields** | **0** | All required columns populated in `manifest.csv` |
| **Invalid / Inaccessible URLs** | **0** | All 40 URLs point to official Indian regulatory domains |

---

## 2. Document Modality & Extraction Classification

Each document in the manifest is categorized based on its primary visual structure:

| Document Type | Count | Total Pages | Typical Structural Characteristics |
|---|:---:|:---:|---|
| **`text_native`** | **24** | **921** | High-density digital text, single-column clauses, and nested numbered sections. Native font streams present. |
| **`table_focused`** | **8** | **183** | High proportion of tabular fee matrices, reporting schedules, and financial ratios with merged headers. |
| **`scanned`** | **8** | **19** | Pure raster/scanned Gazette notifications and administrative appointments from DFS/GOI. Requires OCR fallback. |
| **Total** | **40** | **1,123** | |

---

## 3. High-Complexity Document Classifications

### 3.1 Documents Longer than 50 Pages (7 Documents)
1. `rbi_misc_directions_2025.pdf` — **167 pages** (Reserve Bank of India Miscellaneous Directions)
2. `rbi_forthcoming_instructions_2025.pdf` — **105 pages** (Compendium of Forthcoming Regulatory Instructions)
3. `rbi_mpr_oct_2026.pdf` — **99 pages** (Monetary Policy Report, macroeconomic analysis)
4. `rbi_credit_risk_std_2026.pdf` — **85 pages** (Basel III Credit Risk Standardised Approach Master Direction)
5. `rbi_asset_class_irac_2026.pdf` — **81 pages** (Prudential Norms on Income Recognition, Asset Classification & Provisioning - IRAC)
6. `rbi_primary_dealers_2018.pdf` — **70 pages** (Master Direction on Standalone Primary Dealers)
7. `dfs_nabfid_rules_2022.pdf` — **68 pages** (NaBFID Terms and Conditions of Service Rules)

### 3.2 Two-Column Layout Documents (3 Documents)
1. `rbi_bulletin_economy_oct2026.pdf` — Two-column academic journal format with full-width abstract banners.
2. `rbi_bulletin_speech_oct2026.pdf` — Two-column keynote address format.
3. `dfs_nabfid_rules_2022.pdf` — Two-column bilingual Gazette format (Hindi on left, English on right).

### 3.3 Table-Heavy Documents (8 Documents)
1. `rbi_disbursement_pension_2026.pdf` — Contains multi-page Annex II with 23 repealed circular rows.
2. `rbi_agency_banks_comm_2026.pdf` — Annex 1 (33 agency banks listed) and Annex 2B (CA audit tables).
3. `irdai_cap_structure_2026.pdf` — Fee schedule matrices and Schedule I repealed circulars.
4. `rbi_asset_class_irac_2026.pdf` — Complex NPA provisioning percentage matrices.
5. `rbi_credit_risk_std_2026.pdf` — Risk weight percentage tables by external rating grade.
6. `rbi_market_risk_2026.pdf` — Capital charge computation formulas and risk bucket tables.
7. `rbi_cva_framework_2026.pdf` — Credit Valuation Adjustment supervisory haircut tables.
8. `sebi_currency_deriv_limits_2026.pdf` — Gross open position limit tables across currency pairs.

---

## 4. Issuer Distribution

| Issuing Authority | Abbreviation | Document Count | Total Pages | Percentage of Corpus |
|---|:---:|:---:|:---:|:---:|
| **Reserve Bank of India** | **RBI** | **22** | **731** | 55.0% of docs (65.1% of pages) |
| **Department of Financial Services** | **DFS/GOI** | **9** | **202** | 22.5% of docs (18.0% of pages) |
| **Securities and Exchange Board of India** | **SEBI** | **8** | **174** | 20.0% of docs (15.5% of pages) |
| **Insurance Regulatory and Development Authority** | **IRDAI** | **1** | **16** | 2.5% of docs (1.4% of pages) |
| **Total** | | **40** | **1,123** | **100.0%** |

---

## 5. Metadata and Integrity Verification

- **URL Integrity**: Every entry in `manifest.csv` features a verifiable HTTPS URL originating from official regulatory domain names (`rbidocs.rbi.org.in`, `sebi.gov.in`, `financialservices.gov.in`, `irdai.gov.in`).
- **File Hashing**: Every downloaded PDF has been audited against its recorded SHA-256 checksum in `manifest.csv`. No corrupt or partial downloads exist.
- **Copyright & License Audit**: Indian public regulatory circulars and gazettes fall under Section 52(1)(q) of the Indian Copyright Act, 1957 (acts not constituting infringement: reproduction or publication of any matter published in any Official Gazette or any act of a Legislature).

