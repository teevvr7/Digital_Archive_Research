# Capstone Project Plan: InvoiceInsight RAG System

This document outlines the detailed architecture, dataset plan, and evaluation metrics for **InvoiceInsight**, a standalone RAG chatbot optimized for financial invoices and receipts. This project satisfies all **LLM-Zoomcamp Capstone** grading requirements while acting as a direct algorithm and query sandbox for the **DataWiz Digital Archive** system.

---

## 1. Problem Statement & Scope

Small and Medium Businesses (SMBs) handle hundreds of unstructured PDF invoices and receipts monthly. Standard text-based RAG engines perform poorly on these documents because:
1. Invoices are **tabular and sparse**, meaning simple character-based chunking (e.g., 500 characters) cuts line items in half, destroying retrieval precision.
2. Users ask structural questions (e.g., *"What was the unit cost of laptops purchased from Acme?"*) that require retrieving line items paired with their header details (vendor, invoice date).

**InvoiceInsight** solves this by implementing and evaluating a **Structured-Aware Chunker** and a **Hybrid Vector + Keyword Search** pipeline in a lightweight, containerized Streamlit application.

---

## 2. Technical Architecture & Tech Stack

The application will be developed as a completely independent, containerized service:

```
                  ┌──────────────────────────────────────────────┐
                  │           Streamlit Frontend (UI)            │
                  └──────────────────────┬───────────────────────┘
                                         │
                                         ▼
                  ┌──────────────────────────────────────────────┐
                  │             FastAPI Backend (API)            │
                  └──────────────────────┬───────────────────────┘
                                         │
                                         ▼
                  ┌──────────────────────────────────────────────┐
                  │    Ingestion, Search & RAG Services (Python) │
                  └────┬────────────────────┬───────────────┬────┘
                       │                    │               │
                       ▼                    ▼               ▼
           ┌───────────────────────┐  ┌──────────┐  ┌───────────────┐
           │ PostgreSQL + pgvector │  │minsearch │  │  LLM (Gemini/ │
           │   (Docker DB Store)   │  │(Memory)  │  │  OpenAI/Oll)  │
           └───────────────────────┘  └──────────┘  └───────────────┘
```

* **Frontend**: **Streamlit** for a clean chat interface, document selection, and a performance monitoring dashboard.
* **Database & Knowledge Base**: **PostgreSQL** with the **pgvector** extension. A lightweight, in-memory **minsearch** index will also be implemented to serve as a baseline comparison.
* **LLM Engine**: **Google Gemini API** (recommended for low-cost, high-context generation) or **OpenAI API**.
* **Orchestration / Ingestion**: A Python-based ingestion script that reads synthetic invoice data, chunks it, generates embeddings using a local `SentenceTransformer` (`all-MiniLM-L6-v2`), and inserts it into Postgres.
* **Containerization**: A `docker-compose.yml` defining:
  - `web`: Streamlit + FastAPI application.
  - `db`: PostgreSQL image pre-loaded with `pgvector`.

---

## 3. Ingestion & Chunking Strategy

To prove RAG viability on financial data, the ingestion pipeline will support two chunking strategies for evaluation:

1. **Naive Chunking (Baseline)**: Character-based recursive splitting (500 characters, 100 character overlap).
2. **Structured-Aware Chunking (Proposed)**: Converts invoice JSON fields into structured text records before embedding.
   * *Example*:
     ```
     Document: INV-2026-001 (Vendor: TechCorp, Date: 2026-07-14)
     Chunk 1: "Vendor: TechCorp | Invoice: INV-2026-001 | Date: 2026-07-14 | Line Item: 5x Lenovo ThinkPad Laptops | Unit Price: $1,200.00 | Line Total: $6,000.00"
     Chunk 2: "Vendor: TechCorp | Invoice: INV-2026-001 | Date: 2026-07-14 | Summary: Subtotal: $6,000.00 | Tax (GST 8%): $480.00 | Grand Total: $6,480.00"
     ```

---

## 4. Search & Retrieval Pipeline

To hit the course's best-practice requirements, the retrieval flow will implement:
1. **Vector Search**: Cosine similarity using `pgvector` on the 384-dimensional embeddings.
2. **Keyword Search**: Full-text search or TF-IDF using `minsearch`.
3. **Hybrid Search**: Ranks documents by combining vector similarity scores and keyword search scores.
4. **Re-ranking**: Uses a lightweight cross-encoder model (e.g., `cross-encoder/msmarco-MiniLM-L6-cos-v5`) to re-rank the top-10 retrieved chunks down to the top-3 before feeding them to the LLM.

---

## 5. Evaluation & Monitoring Plan

### 5.1 Retrieval & LLM Evaluation
We will create a ground-truth dataset of 50-100 questions and expected answers based on our synthetic invoices. A Jupyter notebook (`evaluate.ipynb`) will run evaluations using:
* **Retrieval Metrics**: **Hit Rate** and **Mean Reciprocal Rank (MRR)** comparing Naive Chunks vs. Structured Chunks, and Vector vs. Hybrid search.
* **LLM Metrics (LLM-as-a-judge)**:
  * *Faithfulness*: Does the answer use *only* the retrieved context?
  * *Answer Relevance*: Does the answer address the question?

### 5.2 Live Monitoring Dashboard
The Streamlit app will include a dashboard with 5 charts:
1. **User Satisfaction Score**: Percentage of positive vs. negative feedback clicks (thumbs up/down).
2. **Response Latency**: Average response time per query (in seconds) over time.
3. **Token Usage & Cost**: Daily model API costs.
4. **Retrieval Score Distribution**: Cosine similarity scores of top retrieved contexts.
5. **Query Category Mix**: Distribution of questions (e.g., Vendor Info, Line Items, Tax/Totals).

---

## 6. How this Sandbox Feeds Back into DataWiz

The sandbox answers several architectural concerns flagged in [feature_note_01.md](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/nalan_plan/feature_note_01.md):

* **Structured Chunking**: The code in `chunker.py` will be copy-pasted directly into the DataWiz ingestion worker.
* **pgvector Query Syntax**: The raw SQL/SQLAlchemy queries tested in the sandbox (including hybrid search and RLS mocks) can be safely migrated to the FastAPI backend.
* **Local Embeddings RAM Footprint**: Running the sandbox will confirm if the `all-MiniLM-L6-v2` model fits comfortably within the RAM bounds of a low-cost container instance.

---
---

# Expert Review: Flaws, Pitfalls, and Recommendations

> **Reviewer role**: Practical RAG engineer evaluating this plan against the LLM-Zoomcamp capstone rubric, real-world RAG failure modes, and the DataWiz sandbox goal.

---

## A. Critical Flaws Found

### A1. The Architecture is Over-Engineered for the Capstone

The plan describes **three layers** (Streamlit → FastAPI → Services) plus **two search backends** (pgvector + minsearch) in **one docker-compose**. This is too many moving parts for a capstone project that needs to be:
- Cloneable by a stranger in under 5 minutes.
- Reviewable by a peer who will spend 15–30 minutes on it.
- Reproducible on a laptop without GPU.

**The FastAPI middle layer adds nothing here.** Streamlit can call Python functions directly. A separate API server only makes sense in the DataWiz production system (which has a real frontend). In the sandbox, it doubles the code surface, doubles the Dockerfile complexity, and creates confusion for reviewers ("which port do I hit?").

> **Fix**: Drop FastAPI entirely for the Capstone. Streamlit directly imports the Python service modules. Reserve FastAPI integration for when you port the tested code back into DataWiz.

---

### A2. The Dataset Strategy is Dangerously Vague

The plan says "synthetic invoice data" and "100 generated documents" but does not specify:
1. **What format** the data is in. JSON? PDF? Plain text?
2. **How the generator works**. Hand-coded templates? LLM-generated?
3. **How ground-truth Q&A pairs are created** for evaluation.

This is a critical gap because:
- If the dataset is just flat JSON (not text that needs parsing), the "chunking" comparison becomes meaningless — structured JSON is already structured, so "structured-aware chunking" would trivially win against naive text chunking.
- If the dataset is LLM-generated, the evaluation becomes circular (LLM generates data → LLM evaluates its own data).
- If the dataset does not ship with the repo, the reviewer gives **0 points for Reproducibility**.

> **Fix**: Generate the dataset as **realistic invoice text blobs** (not parsed JSON). Use a Python script with `Faker` + templates to create 100-200 invoices as plain text files mimicking OCR output (messy, with line-item tables, varying formats). Ship the generator script AND the pre-generated dataset in the repo under `data/`. Create a separate `data/ground_truth.csv` with 50-100 question-answer pairs manually curated or semi-automated with an LLM and human-verified.

---

### A3. "Structured-Aware Chunking" is Not Actually RAG Chunking

The example in Section 3 shows chunks like:
```
"Vendor: TechCorp | Invoice: INV-2026-001 | Date: 2026-07-14 | Line Item: 5x Lenovo ThinkPad Laptops | Unit Price: $1,200.00 | Line Total: $6,000.00"
```

This is not chunking — this is **template serialisation**. It assumes you already have perfectly parsed structured data (vendor, invoice number, line items). But the whole point of the IDP pipeline is that this structured data may not exist yet, or may be incomplete.

In a real RAG scenario on raw invoice text, you would be chunking the **raw extracted text**, not the post-extraction JSON. The "structured-aware" approach only works if you have ground-truth structured data to begin with — which means you are testing the RAG on already-solved data.

> **Fix**: Separate the two scenarios clearly:
> 1. **Raw Text Chunking** (the primary RAG use case): Chunk the raw invoice text (as-if OCR output). This is what matters for DataWiz.
> 2. **Metadata-Enriched Chunking** (the enhancement): Prepend known metadata (vendor name, invoice number) to each raw text chunk as a header. This is a legitimate technique (used in production RAG systems) and gives each chunk context about which document it belongs to.
>
> The evaluation should compare: (a) raw text chunks, (b) metadata-enriched text chunks, (c) vector vs keyword vs hybrid search across both.

---

### A4. Hybrid Search Implementation is Underspecified

The plan says "combining vector similarity scores and keyword search scores" but does not address:
- **Score normalisation**: Vector cosine similarity returns 0–1. Keyword BM25/TF-IDF returns unbounded scores. You cannot just add them. You need min-max normalisation or Reciprocal Rank Fusion (RRF).
- **Which keyword engine**: The plan says "minsearch" for keywords. But if Postgres is already there with `tsvector` + `pg_trgm`, you have a real, production-grade keyword engine. Using minsearch adds no value beyond being a course reference.

> **Fix**: Use **Reciprocal Rank Fusion (RRF)** to merge vector and keyword results. It is simple, parameter-free, and well-proven:
> ```python
> def rrf_score(rank, k=60):
>     return 1.0 / (k + rank)
>
> # Merge vector_results and keyword_results by document_id
> # Final score = rrf_score(vector_rank) + rrf_score(keyword_rank)
> ```
> For keyword search, use **Postgres FTS** (`tsvector`) if Postgres is already in the docker-compose. Use `minsearch` only as an in-memory alternative for the evaluation notebook (to show you tested multiple retrieval approaches).

---

### A5. Re-ranking with a Cross-Encoder Will Blow Up Docker Image Size

`cross-encoder/msmarco-MiniLM-L6-cos-v5` requires `sentence-transformers` + `torch` + ONNX or PyTorch. This adds **1.5–2 GB** to the Docker image. For a capstone project where reviewers clone and build locally, this is painful.

> **Fix**: Either:
> 1. **Use a lightweight re-ranker** like `flashrank` (pip-only, ~50 MB, no torch dependency). It uses ONNX runtime and achieves comparable quality.
> 2. **Use LLM-based re-ranking** as a simpler alternative: send the top-10 chunks to the LLM and ask it to pick the top-3 most relevant. This counts as re-ranking for the rubric and requires no extra model.
> 3. Or simply **evaluate re-ranking in the notebook** without deploying it in the live app. The rubric says "at least evaluating it" for the bonus point.

---

### A6. No Query Rewriting Mentioned

The capstone rubric awards **1 bonus point** for query rewriting. The plan does not mention it at all.

> **Fix**: Add a simple query rewriting step before retrieval. Example:
> ```python
> def rewrite_query(original_query: str, llm) -> str:
>     prompt = f"""Rewrite this user question to be more specific for searching
>     a database of invoices and receipts. Keep it concise.
>     Original: {original_query}
>     Rewritten:"""
>     return llm.generate(prompt)
> ```
> This is trivial to implement and earns a bonus point.

---

## B. Capstone Rubric Gap Analysis

| Rubric Item | Max | Current Plan Status | Risk |
| :--- | :---: | :--- | :--- |
| Problem description | 2 | ✅ Well-described | Low |
| Retrieval flow (KB + LLM) | 2 | ✅ pgvector + Gemini/OpenAI | Low |
| Retrieval evaluation (multiple approaches) | 2 | ⚠️ Planned but underspecified | Medium — need to actually show results in a notebook |
| LLM evaluation (multiple prompts) | 2 | ⚠️ Only one prompt mentioned | **High** — must test at least 2 prompt strategies |
| Interface (UI) | 2 | ✅ Streamlit | Low |
| Ingestion pipeline (automated) | 2 | ✅ Python script | Low |
| Monitoring (feedback + 5 charts) | 2 | ⚠️ Charts planned but no persistence design | Medium — where is feedback stored? |
| Containerization (full docker-compose) | 2 | ⚠️ Over-engineered (Streamlit + FastAPI + DB) | Medium — simplify |
| Reproducibility | 2 | ❌ Dataset not yet specified as shipped | **High** — must ship data in repo |
| Hybrid search (bonus) | 1 | ⚠️ Planned but no score fusion strategy | Medium |
| Re-ranking (bonus) | 1 | ⚠️ Model too heavy for Docker | Medium |
| Query rewriting (bonus) | 1 | ❌ Not mentioned | **Easy fix** |

### Key gaps to close:
1. **LLM evaluation**: Test at least 2 different system prompts (e.g., "concise answer" vs. "detailed with source citations") and compare using LLM-as-a-judge. Document results.
2. **Monitoring persistence**: Feedback (thumbs up/down) and query logs must be stored in the Postgres database (a `conversations` or `feedback` table), not just in Streamlit session state.
3. **Reproducibility**: The generated dataset + ground truth Q&A must be committed to the repo.

---

## C. Practical Pitfalls to Watch For

### C1. Gemini API Free Tier Rate Limits
Google Gemini's free tier has strict rate limits (e.g., 15 requests/minute for `gemini-2.0-flash`). If the evaluation notebook runs 100 questions in a loop, it will hit rate limits and fail. Plan for:
- Adding `time.sleep(4)` between calls in evaluation scripts.
- Or using a local model via **Ollama** for batch evaluation (free, unlimited, no API key needed).

### C2. pgvector on Supabase Free Tier
Supabase free tier allows 500 MB of database storage. Each 384-dimensional float vector = 1,536 bytes. With 200 invoices × 10 chunks each = 2,000 rows × 1.5 KB ≈ **3 MB of vector data**. This is fine. But if you scale to 10,000 documents in DataWiz, that becomes 150 MB of vectors alone — approaching the limit. Note this for future planning.

### C3. SentenceTransformer Cold Start in Docker
The `all-MiniLM-L6-v2` model is ~80 MB. On first load in a Docker container, it downloads from HuggingFace Hub (network required). If the reviewer runs `docker-compose up` without internet, it fails.

> **Fix**: Pre-download the model during the Docker build step:
> ```dockerfile
> RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
> ```

### C4. Streamlit Session State is Ephemeral
Streamlit reruns the entire script on every interaction. If you store feedback or chat history only in `st.session_state`, it is lost when the user refreshes. For the monitoring dashboard to show real data, all feedback must be written to the database.

---

## D. Suggested Simplified Architecture

Based on all the above, here is a leaner, more practical architecture:

```
┌──────────────────────────────────────────────┐
│         Streamlit App (all-in-one)            │
│  ├── Chat Page (Q&A with sources)            │
│  ├── Upload/Ingest Page                      │
│  └── Monitoring Dashboard (5 charts)         │
└─────────────────────┬────────────────────────┘
                      │ Direct Python calls
                      ▼
┌──────────────────────────────────────────────┐
│            Python Service Layer               │
│  ├── ingest.py    (chunk + embed + store)    │
│  ├── search.py    (vector / keyword / hybrid)│
│  ├── rag.py       (retrieve + prompt + LLM)  │
│  └── evaluate.py  (offline evaluation)       │
└──────┬─────────────────────────┬─────────────┘
       │                         │
       ▼                         ▼
┌─────────────────┐    ┌──────────────────────┐
│ PostgreSQL      │    │ LLM API              │
│ + pgvector      │    │ (Gemini / OpenAI     │
│ (Docker)        │    │  / Ollama)           │
└─────────────────┘    └──────────────────────┘
```

**What changed:**
- Removed FastAPI (not needed for the capstone; reintroduce when porting to DataWiz).
- Removed `minsearch` from the live app (use it only inside `evaluate.py` notebook as a baseline comparison).
- Single Docker service for the app, single Docker service for Postgres.

**Repo structure:**
```
invoice-insight/
├── README.md                    # Full documentation (screenshots, setup, rubric mapping)
├── docker-compose.yml           # Postgres + App
├── Dockerfile                   # Streamlit app
├── requirements.txt             # Pinned versions
├── .env.example                 # API keys template
├── data/
│   ├── generate_dataset.py      # Faker-based invoice text generator
│   ├── invoices/                # 200 pre-generated invoice text files
│   └── ground_truth.csv         # 100 Q&A pairs for evaluation
├── app/
│   ├── streamlit_app.py         # Main Streamlit UI
│   ├── ingest.py                # Chunking + embedding + DB insert
│   ├── search.py                # Vector, keyword, hybrid, RRF
│   ├── rag.py                   # Retrieval + prompt building + LLM call
│   ├── db.py                    # Postgres connection + schema
│   └── config.py                # Settings from env vars
├── notebooks/
│   ├── evaluation_retrieval.ipynb   # Compare chunking + search strategies
│   └── evaluation_llm.ipynb         # Compare prompt templates (LLM-as-judge)
└── monitoring/
    └── dashboard.py             # Streamlit page for 5 monitoring charts
```

---

## E. Additional Advice

### E1. Start with the Evaluation Notebook, Not the App
Counter-intuitive, but: build `evaluation_retrieval.ipynb` first. Get the chunking, embedding, and search working in a notebook. Measure Hit Rate and MRR. Only then wrap it in Streamlit. This avoids the trap of building a pretty UI over broken retrieval.

### E2. Conversation Memory is Not Required for the Capstone
The rubric does not mention multi-turn conversation. A single-turn Q&A interface is sufficient for full marks. Do not waste time on session management, chat history tables, or context window management. Keep it simple: one question in, one answer out (with source chunks shown).

### E3. The "Document-Level vs. Archive-Level" Distinction Matters
For the capstone, keep the scope to **archive-level Q&A** ("Ask questions across all your invoices"). Do not implement document-level chat (selecting a specific invoice to ask about). Archive-level is simpler and more impressive for the rubric. Document-level filtering can be added later when porting to DataWiz (where you have per-document URLs and RLS isolation).

### E4. Use Ollama as the Default LLM for Reproducibility
If the reviewer does not have a Gemini or OpenAI API key, the app should still work. Configure Ollama (`llama3.2` or `qwen2.5:3b`) as the default, with Gemini/OpenAI as optional upgrades. Ollama runs locally, requires no API key, and the reviewer can `docker run ollama/ollama` alongside your app. This maximises reproducibility points.

### E5. Pin Every Dependency Version
The rubric explicitly states: *"The versions for all dependencies are specified"* for full reproducibility points. Use `pip freeze > requirements.txt` after development, not loose version ranges. Include Python version in the Dockerfile (`FROM python:3.11-slim`).

### E6. Record a 60-Second App Demo Video
The capstone guidelines explicitly recommend a video for Streamlit apps. Use Streamlit's built-in recorder or a screen capture tool. Upload the `.webm` to the repo and embed it in the README. This dramatically improves reviewer experience and earns goodwill.

---

## F. Summary Verdict

The InvoiceInsight concept is **sound and well-aligned** with both the capstone requirements and the DataWiz R&D goals. The core issues are:

1. **Over-engineering** (FastAPI layer, dual search backends in the live app) — simplify.
2. **Dataset vagueness** — must generate and ship realistic text data, not pre-parsed JSON.
3. **Evaluation gaps** — must test multiple prompts for LLM evaluation, add query rewriting for bonus.
4. **Docker weight** — avoid heavy cross-encoder models; use lighter alternatives.
5. **Missing persistence** — feedback and logs must go to the database, not session state.

If these are addressed, the project should comfortably score **18-21 out of 21 base points** plus **2-3 bonus points**.
