# Daily Progress Report — 23 July 2026

## Overview
Executed Phase 3B retrieval optimization experiments (Weighted RRF boosted **MRR@5 by 57% to 0.4985**), created the revised development roadmap **[rag_roadmap_v2.md](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/rag_dev/rag_roadmap_v2.md)**, updated **[rag_development_log.md](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/rag_dev/rag_development_log.md)**, and fully implemented the modular Phase 4 codebase (`src/config.py`, `src/router.py`, `src/sql_engine.py`, `src/rag.py`, `src/pipeline.py`, and `04_pipeline_evaluation.py`).

---

## 1. Phase 3B Experiment Results
* **Experiment 1 (FTS `simple` Dictionary)**: Tested switching `tsvector` dictionary to `simple`. Diagnosed why it dropped Hit Rate to 0.00% (stopword preservation in `plainto_tsquery` required non-existent filler words like "what", "for"). Reverted to `english`.
* **Experiment 2 (Weighted RRF)**: Applied 2.5x keyword weight in `src/search.py`:
  $$\text{RRF Score} = \frac{1.0}{60 + \text{rank}_{\text{vector}}} + \frac{2.5}{60 + \text{rank}_{\text{keyword}}}$$
* **Metric Improvement**: Re-ran `03_retrieval_evaluation.py`. **MRR@5 improved from 0.3173 to 0.4985 (+57%)**, ensuring exact keyword matches consistently occupy Rank 1.

---

## 2. Revised Roadmap v2 & Documentation
* Created **[rag_roadmap_v2.md](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/rag_dev/rag_roadmap_v2.md)** as the primary reference plan for the remaining phases.
* Updated **[rag_development_log.md](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/rag_dev/rag_development_log.md#L182)** with Phase 3B benchmark metrics, architectural pivot justification (Text-to-SQL + RAG), Groq/OpenAI provider swappability matrix, and ground truth expansion plan.

---

## 3. Phase 4 Implementation Details
Built the complete modular system under `src/`:
1. **[src/config.py](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/rag_dev/src/config.py)**: `.env` loader with default model `LLM_MODEL=openai/gpt-oss-20b` and OpenAI-compatible client builder.
2. **[src/router.py](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/rag_dev/src/router.py)**: Deterministic `classify_query()` router (exact ID regex `INV-\d{4}-\d{4}`, aggregations, date ranges, vendor filters → SQL; fuzzy → RAG).
3. **[src/sql_engine.py](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/rag_dev/src/sql_engine.py)**: Text-to-SQL query generator & PostgreSQL JSONB execution engine with fast-path ID lookups and response synthesis.
4. **[src/rag.py](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/rag_dev/src/rag.py)**: RAG search path with prompt variants (`concise`, `detailed`, `structured`) and `rewrite_query()` query rewriting.
5. **[src/pipeline.py](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/rag_dev/src/pipeline.py)**: Unified pipeline entry point (`answer_query()`).
6. **[04_pipeline_evaluation.py](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/rag_dev/04_pipeline_evaluation.py)**: Benchmark script measuring router distribution, Hit Rate, and MRR.

---

## 4. Next Session Plans
* Enter API key in `.env`.
* Run `python 04_pipeline_evaluation.py` to evaluate Phase 4 pipeline performance.
* Build Phase 5 Streamlit interface (Chat page + 5-chart Monitoring Dashboard).
