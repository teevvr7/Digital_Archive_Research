# Daily Progress Report — 21 July 2026

## Overview
Executed the **Phase 3: Retrieval Evaluation** benchmark across 149 ground-truth questions. Discovered key empirical insights regarding vector search failures on alphanumeric document IDs, analyzed Reciprocal Rank Fusion (RRF) score dilution mechanisms, and documented findings and three concrete optimization strategies in the project development log.

---

## 1. Benchmark Execution Results
Executed `03_retrieval_evaluation.py` measuring **Hit Rate@5** and **MRR@5**:
* **Vector Search (Cosine)**: Hit Rate **4.70%**, MRR **0.0234**
* **Keyword Search (FTS)**: Hit Rate **48.32%**, MRR **0.4832**
* **Hybrid Search (RRF)**: Hit Rate **51.68%**, MRR **0.3173**

---

## 2. Experimental Analysis & Insights
* **Vector Search Limitation**: Dense embedding models (`all-MiniLM-L6-v2`) capture semantic meaning but are blind to unique alphanumeric identifiers (e.g., `INV-2026-0145`).
* **Keyword Search Strength & Cap**: FTS matches exact tokens and places matches at Rank 1 (MRR = 0.4832), but is capped at ~48% due to text search dictionary hyphenation rules.
* **Hybrid Search Trade-off**: RRF achieved the highest overall Hit Rate (51.68%), but equal-weight fusion allowed noisy vector candidates to dilute exact keyword match ranks, lowering MRR.

---

## 3. Documentation & Proposed Solutions
* Updated **[rag_development_log.md](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/rag_dev/rag_development_log.md#L136)** with detailed benchmark metrics, root cause analysis, and proposed solutions:
  1. **Weighted RRF**: Apply 2x weight to keyword ranks.
  2. **Regex ID Metadata Filtering**: Pre-parse query strings for invoice ID patterns.
  3. **Search Query Expansion**: Include un-hyphenated invoice IDs in markdown texts.

---

## 4. Next Session Plans
* Implement Weighted RRF and Regex ID filtering inside `src/search.py`.
* Re-run `03_retrieval_evaluation.py` to target 85%+ Hit Rate and 0.75+ MRR.
* Move to Phase 4: Prompt template construction and LLM answer generation.
