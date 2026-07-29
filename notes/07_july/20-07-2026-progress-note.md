# Daily Progress Report — 20 July 2026

## Overview
Resolved Windows environment library initialization issues, completed **Phase 2: Ingestion & Embeddings** database execution, and implemented **Phase 3: Retrieval & Evaluation**. Developed search functions supporting vector similarity, full-text keywords, and Reciprocal Rank Fusion (RRF) hybrid scoring, alongside a benchmark test suite measuring Hit Rate@5 and MRR@5 across 150 test queries.

---

## 1. System Environment & C++ Runtime Resolution
* **DLL Conflict Resolution**: Resolved a Windows dynamic link library crash (`c10.dll` WinError 1114) by updating the base Anaconda environment package manager. This refreshed the system C++ runtime libraries (`MSVCP140.dll`), allowing PyTorch and SentenceTransformer embedding models to initialize cleanly.

---

## 2. Phase 2 Ingestion Execution & Verification
* **Database Vector Ingestion**: Executed the Phase 2 ingestion workflow to vectorize 200 invoice documents into 384-dimensional dense vectors and upsert them into the PostgreSQL vector database.
* **Vector Schema Verification**: Verified stored database record counts and confirmed vector data attributes (`vector(384)` dimension type).

---

## 3. Phase 3 Search Algorithms & Evaluation Suite
* **Vector Search (`src/search.py`)**: Implemented cosine similarity search using `pgvector` distance operators (`<=>`).
* **Keyword Search (`src/search.py`)**: Implemented PostgreSQL Full-Text Search (`tsvector`) using `plainto_tsquery` and GIN-indexed rank scoring (`ts_rank`).
* **Hybrid Search (`src/search.py`)**: Built Reciprocal Rank Fusion (RRF) scoring to combine the top candidate results from both vector and keyword search.
* **Evaluation Script (`03_retrieval_evaluation.py`)**: Constructed a benchmark runner to evaluate 150 ground-truth Q&A rows across **Hit Rate@5** and **MRR@5** metrics.

---

## 4. Next Session Plans
* Run `python 03_retrieval_evaluation.py` to test and compare Hit Rate and MRR accuracy across Vector, Keyword, and Hybrid search algorithms.
* Begin Phase 4: Prompt template construction and LLM answer generation using the self-hosted VLM model.
