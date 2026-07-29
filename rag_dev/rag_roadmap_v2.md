# InvoiceInsight RAG — Revised Roadmap (v2)

> Replaces the original `rag_roadmap.md`. Incorporates Phase 3 benchmark findings and the Text-to-SQL + RAG hybrid architecture decision. This is the single reference document for all remaining work.

---

## Architecture Decision: Why Hybrid (Text-to-SQL + RAG)

**Phase 3 Benchmark Results** proved that pure RAG retrieval fails on structured invoice data:

```text
Vector Search:  4.70% Hit Rate  |  0.0234 MRR
Keyword Search: 48.32% Hit Rate |  0.4832 MRR
Hybrid RRF:     51.68% Hit Rate |  0.3173 MRR
```

**Root cause**: Invoice queries fall into two distinct categories that require fundamentally different retrieval strategies:

| Query Type | Example | What Works | What Fails |
|---|---|---|---|
| **Structured** (aggregation, filtering, lookups) | "Total sales of Laptops last month" | SQL against JSONB | RAG (cannot scan all 200 docs) |
| **Fuzzy / Contextual** (user doesn't know exact IDs) | "I bought equipment from a hardware store around March" | Vector similarity | SQL (no exact terms to filter on) |

**Solution**: A lightweight **query router** dispatches to either a **Text-to-SQL engine** or the existing **RAG pipeline**. No agents. No function-calling. Just a rule-based Python `if/else` that inspects the query and picks the right path.

```
User Query → Router (rule-based, ~20 lines of Python)
                ├── Structured query → LLM generates SQL → Execute → Format answer
                └── Fuzzy query      → RAG (embed → retrieve → LLM answer)
```

### Is This an "Agent"?

No. This is a **router**, not an agent. An agent would autonomously decide which tools to call, chain multiple steps, and reason about intermediate results. Our router is a deterministic `if/else` classifier — simple, predictable, debuggable.

However, the rubric says: *"It can be a RAG application, an agent application, or a combination of both."* Our system is a **combination**: it has a RAG path AND a structured query path, unified under a single interface. This is architecturally stronger than pure RAG and fully satisfies the rubric.

### Capstone Rubric Coverage

| Rubric Item | Max | How We Cover It |
|---|:---:|---|
| Problem description | 2 | Structured data RAG challenge, documented with benchmark evidence |
| Retrieval flow (KB + LLM) | 2 | Knowledge base (pgvector + JSONB) + LLM (OpenAI-compatible) |
| Retrieval evaluation (multiple approaches) | 2 | Vector vs FTS vs Hybrid RRF vs Text-to-SQL — 4 approaches compared |
| LLM evaluation (multiple prompts) | 2 | Test 2-3 prompt variants with LLM-as-a-judge |
| Interface (UI) | 2 | Streamlit chat + monitoring dashboard |
| Ingestion pipeline (automated) | 2 | Python script (`02_ingestion.py` / `src/ingest.py`) |
| Monitoring (feedback + 5 charts) | 2 | Feedback table + 5 Streamlit charts from `feedback` table |
| Containerization | 2 | Full `docker-compose.yml` (app + db) |
| Reproducibility | 2 | Shipped dataset, pinned deps, clear README |
| **Bonus**: Hybrid search | 1 | Vector + FTS + RRF already implemented and evaluated |
| **Bonus**: Re-ranking | 1 | LLM-based re-ranking in evaluation notebook |
| **Bonus**: Query rewriting | 1 | LLM rewrites query before retrieval |

**Projected score: 20-23 / 24**

---

## What Changes from the Original Roadmap

| Phase | Original Plan | What Changes |
|:---:|---|---|
| 1 | Foundations (data + DB) | **No change.** Already completed. |
| 2 | Ingestion (embed + store) | **No change.** Already completed. |
| 3 | Retrieval evaluation | **Completed.** Benchmark results documented. |
| 3B | **NEW**: Retrieval improvements | Fix FTS tokenization + add weighted RRF. Re-run benchmark. |
| 4 | LLM Generation | **Expanded.** Split into two sub-paths: RAG answer generation + Text-to-SQL generation. Add query router. |
| 5 | Streamlit UI | **Simplified.** Single chat page routes to either path. Add monitoring dashboard. |
| 6 | Containerization + README | **No major change.** Add Dockerfile, full docker-compose, demo video. |
| 7 | Bonus (re-rank, rewrite) | **Simplified.** LLM-based re-ranking (no heavy cross-encoder). Query rewriting via LLM prompt. |

---

## Phase 3B — Retrieval Improvements (NEW)

> **Goal**: Push Hit Rate above 80% and MRR above 0.70 before moving to LLM generation.

### Step 3B.1 — Fix FTS Tokenization
Change the `tsvector` dictionary from `english` to `simple` so hyphenated invoice IDs (`INV-2026-0145`) are preserved as whole tokens instead of being split.

**Requires**: Schema change in `init.sql`, re-run `docker-compose down -v && docker-compose up -d`, re-ingest data.

### Step 3B.2 — Weighted RRF
Give keyword search ranks 2.5x weight over vector ranks in `hybrid_search()`.

### Step 3B.3 — Re-run Benchmark
Execute `03_retrieval_evaluation.py` again. Compare improved results against the original baseline. Document both in the development log.

**Deliverable**: Updated benchmark table showing before/after metrics.

---

## Phase 4 — Query Router + LLM Generation (REVISED)

> **Goal**: Full working system — question in, answer out — using the optimal path for each query type.

### Step 4.1 — Text-to-SQL Path (`src/sql_engine.py`)

Create a new module that:
1. Receives a user query classified as "structured".
2. Sends the JSON schema (field names only, not data) to the LLM.
3. LLM generates a PostgreSQL query using `content_json->>` JSONB operators.
4. Executes the query against the database (read-only).
5. Formats the SQL result into a natural language answer via a second LLM call.

```python
SCHEMA_PROMPT = """You have a PostgreSQL table `invoice_chunks` with a JSONB column `content_json`.
The JSON fields are: invoice_id, vendor, date, buyer, buyer_address, subtotal, tax_rate, tax,
grand_total, currency, payment_terms, line_items[].description, line_items[].qty,
line_items[].unit_price, line_items[].amount.

Write a single PostgreSQL SELECT query to answer the user's question.
Use content_json->>'field' for text fields and (content_json->>'field')::numeric for numbers.
For line_items (a JSONB array), use jsonb_array_elements(content_json->'line_items') to unnest.
Return ONLY the SQL query, nothing else."""
```

### Step 4.2 — RAG Answer Path (`src/rag.py`)

Implement the standard RAG generation function:
1. Receives a user query classified as "fuzzy/contextual".
2. Calls `hybrid_search()` to retrieve top-5 document chunks.
3. Builds a prompt with the retrieved context.
4. Sends to LLM and returns the generated answer.

### Step 4.3 — Query Router (`src/router.py`)

A simple rule-based classifier (~20 lines):

```python
import re

def classify_query(query: str) -> str:
    q = query.lower()
    # Aggregation keywords
    if any(kw in q for kw in ["total", "sum", "how many", "count", "average",
                                "highest", "lowest", "most", "least", "all invoices"]):
        return "sql"
    # Date range filtering
    if any(kw in q for kw in ["last month", "this month", "in march", "between",
                                "from january", "in 2026", "in 2025"]):
        return "sql"
    # Vendor/buyer filtering
    if any(kw in q for kw in ["from vendor", "all from", "invoices from",
                                "show me all", "list all"]):
        return "sql"
    # Explicit invoice ID → direct SQL lookup
    if re.search(r'INV-\d{4}-\d{4}', query, re.IGNORECASE):
        return "sql"
    # Default: fuzzy/contextual → RAG
    return "rag"
```

### Step 4.4 — Unified Entry Function (`src/pipeline.py`)

A single function that the Streamlit UI calls:

```python
def answer_query(query: str, model, db_conn) -> dict:
    intent = classify_query(query)
    if intent == "sql":
        result = text_to_sql_answer(query, db_conn)
    else:
        result = rag_answer(query, model, db_conn)
    return {"answer": result["answer"], "method": intent, ...}
```

### Step 4.5 — LLM Evaluation (Multiple Prompts)

Test 2-3 prompt variants for the RAG path using LLM-as-a-judge:
- **Concise**: "Answer in one sentence. Cite the invoice ID."
- **Detailed**: "Answer with full details. Quote exact values."
- **Structured**: "Format: ANSWER: [answer]. SOURCE: [invoice_id]."

Compare average judge scores. Pick the best prompt for the live app.

**Deliverable**: Evaluation notebook `04_llm_evaluation.py` showing prompt comparison results.

---

## Phase 5 — Streamlit UI

> **Goal**: Working chat interface + monitoring dashboard.

### Step 5.1 — Chat Page (`streamlit_app.py`)

- Text input for user question.
- On submit: call `answer_query()` (routed automatically).
- Display: the answer, which method was used (SQL or RAG), and retrieved context (expandable).
- Thumbs up/down buttons → write to `feedback` table.
- Display response time.

### Step 5.2 — Monitoring Dashboard Page

5 charts querying the `feedback` table:
1. Thumbs Up/Down ratio (pie chart)
2. Queries per day (bar chart)
3. Average response time (line chart)
4. Top retrieved invoice IDs (bar chart)
5. Query method distribution: SQL vs RAG (pie chart)

### Step 5.3 — Data Viewer Page (Optional)

Simple `SELECT * FROM invoice_chunks` displayed in `st.dataframe()`.

---

## Phase 6 — Containerization & Reproducibility

> **Goal**: `docker-compose up` runs the full system.

### Step 6.1 — Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
COPY . .
CMD ["streamlit", "run", "streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

### Step 6.2 — Full docker-compose.yml

Two services: `app` (Streamlit) + `db` (pgvector PostgreSQL).

### Step 6.3 — README

- Problem description with architecture diagram.
- Setup instructions.
- Screenshots of Chat and Monitoring pages.
- Rubric self-assessment table.
- Demo video (60-second screencast).

---

## Phase 7 — Bonus Points

> **Goal**: Earn 2-3 bonus points with minimal effort.

### Step 7.1 — Hybrid Search (Already Done) ✅
Vector + FTS + RRF already implemented and benchmarked. **1 bonus point secured.**

### Step 7.2 — LLM-Based Re-Ranking (Evaluation Only)
In notebook only: take top-10 vector results, ask the LLM to score relevance (0-10), re-sort. Compare Hit Rate before/after. No extra models, no Docker weight.

### Step 7.3 — Query Rewriting
Add to `src/rag.py`:
```python
def rewrite_query(original: str) -> str:
    return ask_llm(
        "Rewrite this question to be clearer for searching invoices. Keep it short.",
        f"Original: {original}\nRewritten:"
    )
```
Evaluate: does rewriting improve Hit Rate? Show before/after in notebook.

---

## Revised Timeline

| Phase | What | Status | Est. Hours |
|:---:|---|:---:|:---:|
| 1 | Foundations (data + DB) | ✅ Done | — |
| 2 | Ingestion (embed + store) | ✅ Done | — |
| 3 | Retrieval evaluation (baseline) | ✅ Done | — |
| 3B | Retrieval improvements (FTS fix + weighted RRF) | TODO | 1-2h |
| 4 | Query router + Text-to-SQL + RAG generation + LLM eval | TODO | 4-5h |
| 5 | Streamlit UI (chat + monitoring) | TODO | 3-4h |
| 6 | Docker + README + video | TODO | 2-3h |
| 7 | Bonus (re-rank, rewrite) | TODO | 1-2h |
| | **Remaining Total** | | **~12-16h** |

---

## Files to Create / Modify

| File | Action | Purpose |
|---|:---:|---|
| `src/sql_engine.py` | NEW | Text-to-SQL generation and execution |
| `src/router.py` | NEW | Rule-based query intent classifier |
| `src/pipeline.py` | NEW | Unified entry function (router → SQL or RAG) |
| `src/rag.py` | MODIFY | Implement RAG generation + query rewriting |
| `src/search.py` | MODIFY | Add weighted RRF, fix keyword search |
| `init.sql` | MODIFY | Change tsvector to `simple` dictionary |
| `04_llm_evaluation.py` | NEW | LLM prompt comparison notebook |
| `streamlit_app.py` | MODIFY | Full chat UI + monitoring dashboard |
| `Dockerfile` | NEW | App container |
| `docker-compose.yml` | MODIFY | Add app service |
| `README.md` | NEW | Full project documentation |
