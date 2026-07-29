# Daily Progress Report — 22 July 2026

## Overview
Performed a comprehensive failure analysis of Phase 3 retrieval evaluation results. Identified the fundamental architectural mismatch between structured invoice data (JSONB) and unstructured text RAG, created the **[retrieval_improvement_brainstorm.md](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/rag_dev/retrieval_improvement_brainstorm.md)** ideation document, and formulated a hybrid **Text-to-SQL + RAG** system design managed by a rule-based query intent router.

---

## 1. Core Problem & Analysis
* **Vector Search Baseline Failure**: Dense text embeddings (`all-MiniLM-L6-v2`) capture semantic meaning but are blind to specific alphanumeric document IDs (4.70% Hit Rate).
* **Mismatch in Query Types**: SME business queries fall into structured operations (aggregations like "total spent on Laptops", date filters, vendor lookups) vs fuzzy contextual queries.
* **RAG Limitation**: RAG retrieves top-5 chunks, which inherently fails on multi-document aggregations requiring a scan of all 200 invoices.

---

## 2. Deliverables & Brainstorming Document
Created **[retrieval_improvement_brainstorm.md](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/rag_dev/retrieval_improvement_brainstorm.md)** containing 9 ranked improvement strategies:
1. **Direct JSONB Field Lookup** (Regex ID bypass to SQL) — Effort: 30m
2. **Query Intent Router** (Rule-based routing) — Effort: 1h
3. **Text-to-SQL Generation** (LLM-generated SQL against JSONB) — Effort: 2h
4. **Weighted RRF** (2.5x keyword weighting) — Effort: 15m
5. **Structured Metadata Columns + Pre-Filtering** — Effort: 1.5h
6. **Smarter FTS Tokenization** (Dictionary adjustments) — Effort: 45m
7. **Agentic RAG** (Tool calling) — Effort: 3h
8. **Chunk-per-field Embedding** — Effort: 2h
9. **Hybrid Architecture (SQL + RAG)** — Effort: 3h

---

## 3. Architecture Pivot Decision
Decision: Adopt a **Hybrid Architecture (Text-to-SQL + RAG)** with a rule-based Python query router:
* **Structured Path**: Text-to-SQL for aggregations, ID lookups, date ranges, and vendor filters.
* **Contextual Path**: Hybrid Vector + FTS RAG for fuzzy or non-exact queries.
* **Router**: Deterministic `if/else` classifier (~20 lines of Python) for simplicity, speed, and debuggability.

---

## 4. Next Session Plans
* Run Phase 3B experiments (Weighted RRF & FTS dictionary testing).
* Write `rag_roadmap_v2.md` and log architectural decisions in `rag_development_log.md`.
* Build Phase 4 modular codebase (`src/config.py`, `src/router.py`, `src/sql_engine.py`, `src/rag.py`, `src/pipeline.py`, `04_pipeline_evaluation.py`).
