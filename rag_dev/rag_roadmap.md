# InvoiceInsight RAG — Development Roadmap

> Step-by-step build order. Core RAG functionality first, advanced/bonus features deferred.
> Each phase is self-contained and testable in a notebook before moving forward.

---

## Pre-Build Decisions

### LLM Provider Swappability ✅

The Qwen3-VL endpoint already uses the **OpenAI-compatible API** (via vLLM). This is the universal standard — almost every LLM provider exposes it:

| Provider | Swap How |
| :--- | :--- |
| Self-hosted Qwen3-VL (current) | `base_url=https://YOUR-LIGHTNING.../v1`, `api_key=none` |
| OpenAI | `base_url=https://api.openai.com/v1`, `api_key=sk-...` |
| Groq | `base_url=https://api.groq.com/openai/v1`, `api_key=gsk-...` |
| Ollama (local) | `base_url=http://localhost:11434/v1`, `api_key=none` |
| Together AI | `base_url=https://api.together.xyz/v1`, `api_key=...` |

**Implementation**: A single `config.py` with 3 env vars:

```python
# config.py
import os

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_API_KEY  = os.getenv("LLM_API_KEY", "none")
LLM_MODEL    = os.getenv("LLM_MODEL", "qwen3-vl-4b-instruct")
```

All LLM calls use the `openai` Python client:

```python
from openai import OpenAI
from config import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL

client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)

def ask_llm(system_prompt: str, user_prompt: str, max_tokens: int = 512) -> str:
    resp = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=max_tokens,
        temperature=0,
    )
    return resp.choices[0].message.content
```

**To swap**: change `.env` values. Zero code changes. Works for any OpenAI-compatible endpoint.

---

### JSON Serialisation Strategy ✅

**Problem**: Each document's `extracted_data` JSON has different keys and structures. A hardcoded serialiser breaks on unseen schemas.

**Solution**: A **generic recursive JSON-to-Markdown** converter. Markdown is the better choice over plain text because:
- It preserves hierarchy (headers, lists, tables).
- Embedding models handle markdown well (it is natural language with light formatting).
- When sent as LLM context, markdown is more readable and structured than pipe-separated text.
- It handles **any** JSON shape without hardcoding field names.

```python
def json_to_markdown(data: dict, title: str = "Document") -> str:
    """Convert any JSON dict to readable markdown. Fully schema-agnostic."""
    lines = [f"# {title}", ""]

    for key, value in data.items():
        label = key.replace("_", " ").title()

        if isinstance(value, list) and value and isinstance(value[0], dict):
            # Array of objects → numbered list (e.g., line_items)
            lines.append(f"## {label}")
            for i, item in enumerate(value, 1):
                parts = [f"**{k.replace('_', ' ').title()}**: {v}" for k, v in item.items() if v]
                lines.append(f"{i}. {' | '.join(parts)}")
            lines.append("")

        elif isinstance(value, dict):
            # Nested object → sub-section
            lines.append(f"## {label}")
            for k, v in value.items():
                if v:
                    lines.append(f"- **{k.replace('_', ' ').title()}**: {v}")
            lines.append("")

        elif isinstance(value, list):
            # Simple list (rare)
            lines.append(f"- **{label}**: {', '.join(str(v) for v in value)}")

        else:
            # Scalar
            if value is not None and value != "":
                lines.append(f"- **{label}**: {value}")

    return "\n".join(lines)
```

**Validation with different invoice schemas:**

Input A (standard invoice):
```json
{"vendor": "TechCorp", "invoice_number": "INV-001", "grand_total": 6960.60,
 "line_items": [{"description": "Laptop", "qty": 5, "amount": 6000}]}
```
→ Output A:
```markdown
# Document

- **Vendor**: TechCorp
- **Invoice Number**: INV-001
- **Grand Total**: 6960.6

## Line Items
1. **Description**: Laptop | **Qty**: 5 | **Amount**: 6000
```

Input B (receipt with completely different keys):
```json
{"store_name": "7-Eleven", "receipt_no": "R-9921", "items": [{"name": "Coffee", "price": 5.50}], "total": 5.50}
```
→ Output B:
```markdown
# Document

- **Store Name**: 7-Eleven
- **Receipt No**: R-9921
- **Total**: 5.5

## Items
1. **Name**: Coffee | **Price**: 5.5
```

Input C (contract - no line items at all):
```json
{"parties": "Acme Corp and GlobalTech", "effective_date": "2026-01-01", "terms_conditions": "Net 60 payment terms"}
```
→ Output C:
```markdown
# Document

- **Parties**: Acme Corp and GlobalTech
- **Effective Date**: 2026-01-01
- **Terms Conditions**: Net 60 payment terms
```

**All three schemas work without any changes to the converter.** The function handles any flat JSON, nested objects, and arrays of objects — which covers all IDP extraction output patterns.

---

### Experiment-Ready Design ✅

Every stage is a standalone Python module that can be:
1. **Imported and tested in a Jupyter notebook** independently.
2. **Configured via environment variables** or function arguments (not hardcoded).
3. **Swapped** — each function takes its dependencies as parameters, not globals.

| Stage | What's Tuneable |
| :--- | :--- |
| Data generation | Number of invoices, vendor pool, product pool, price ranges |
| Serialisation | `json_to_markdown()` vs `json_to_text()` — try both, measure embedding quality |
| Embedding model | Swap `all-MiniLM-L6-v2` for any SentenceTransformer model by changing one string |
| Search method | Vector / keyword / hybrid — each is a separate function, compare in notebook |
| RRF k parameter | `k=60` is the standard default, tuneable |
| Number of retrieved chunks | `top_k` parameter on every search function |
| LLM prompt | System prompt is a string variable, test multiple variants |
| LLM provider | 3 env vars (see above) |

---

## Phase 1 — Foundations (Data + Database)

> **Goal**: Have synthetic data ready and a working database. No ML yet.

### Step 1.1 — Project Scaffold

Create the repo structure:

```
invoice-insight/
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── init.sql
├── requirements.txt
├── data/
│   ├── generate_invoices.py
│   └── generate_ground_truth.py
├── app/
│   ├── config.py
│   ├── db.py
│   ├── serialise.py          # json_to_markdown()
│   ├── ingest.py
│   ├── search.py
│   └── rag.py
├── notebooks/
└── streamlit_app.py
```

**Deliverable**: Empty files with docstrings. `config.py` with all env vars. `.env.example`.

### Step 1.2 — Data Generation

Write `generate_invoices.py`:
- Use `Faker` + custom templates.
- Generate 200 invoices as a JSON array.
- Vary: vendor names (20-30), product types (30-40), quantities, prices, tax rates, currencies, dates.
- Save to `data/invoices.json`.

Write `generate_ground_truth.py`:
- Read `invoices.json`.
- For each invoice, generate 2-5 question templates (lookup, line-item, aggregation).
- Produce ~100 Q&A rows in `data/ground_truth.csv`.
- Columns: `question`, `expected_answer`, `source_invoice_id`, `question_type`.

**Deliverable**: `data/invoices.json` + `data/ground_truth.csv` committed to repo. Test by printing a few samples.

### Step 1.3 — Database Setup

Write `init.sql`:

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE invoice_chunks (
    id SERIAL PRIMARY KEY,
    invoice_id TEXT NOT NULL UNIQUE,
    content_text TEXT NOT NULL,
    content_json JSONB NOT NULL,
    embedding vector(384) NOT NULL
);

CREATE INDEX ON invoice_chunks USING hnsw (embedding vector_cosine_ops);

-- Full-text search (for hybrid later)
ALTER TABLE invoice_chunks ADD COLUMN search_tsv TSVECTOR
    GENERATED ALWAYS AS (to_tsvector('english', content_text)) STORED;
CREATE INDEX ON invoice_chunks USING gin (search_tsv);

CREATE TABLE feedback (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    retrieved_ids TEXT[],
    relevance_score REAL,
    response_time_ms INT,
    user_rating INT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

Write `docker-compose.yml` (Postgres only, for now):

```yaml
version: "3.8"
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: invoice_insight
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./init.sql:/docker-entrypoint-initdb.d/init.sql
volumes:
  pgdata:
```

**Deliverable**: `docker-compose up db` creates the database. Verify with `psql` that tables exist.

---

## Phase 2 — Ingestion Pipeline

> **Goal**: Convert JSON invoices → markdown text → embeddings → stored in Postgres.

### Step 2.1 — Serialisation Module

Write `app/serialise.py`:
- Implement `json_to_markdown(data, title)` (generic, schema-agnostic, as designed above).
- **Experiment point**: Also implement a simpler `json_to_text(data)` (flat key-value, no markdown formatting) to compare embedding quality later.

**Test in notebook**: Load a few invoices, serialise both ways, print and visually inspect.

### Step 2.2 — Embedding + Ingestion

Write `app/ingest.py`:

```python
from sentence_transformers import SentenceTransformer

def ingest_invoices(invoices: list[dict], db_conn, model_name: str = "all-MiniLM-L6-v2"):
    model = SentenceTransformer(model_name)   # loaded once

    for inv in invoices:
        text = json_to_markdown(inv, title=f"Invoice {inv.get('invoice_id', 'N/A')}")
        embedding = model.encode(text).tolist()

        db_conn.execute("""
            INSERT INTO invoice_chunks (invoice_id, content_text, content_json, embedding)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (invoice_id) DO NOTHING
        """, (inv["invoice_id"], text, json.dumps(inv), embedding))

    db_conn.commit()
```

**Test in notebook**: Ingest all 200 invoices. Verify row count in DB. Print a few `content_text` values.

**Experiment point**: The `model_name` parameter allows swapping embedding models without changing any other code.

---

## Phase 3 — Retrieval (Core RAG)

> **Goal**: Given a question, retrieve the most relevant invoice chunks. Test and measure in notebook.

### Step 3.1 — Vector Search

Write the vector search function in `app/search.py`:

```python
def vector_search(query: str, model, db_conn, top_k: int = 5):
    q_vec = model.encode(query).tolist()
    rows = db_conn.execute("""
        SELECT invoice_id, content_text, content_json,
               1 - (embedding <=> %s::vector) AS similarity
        FROM invoice_chunks
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """, (q_vec, q_vec, top_k))
    return rows.fetchall()
```

**Test in notebook**: Run 5-10 sample queries. Inspect if the correct invoice appears in top-5 results.

### Step 3.2 — Retrieval Evaluation (Notebook)

Create `notebooks/eval_retrieval.ipynb`:

1. Load ground truth CSV.
2. For each question, run `vector_search()`.
3. Check if `source_invoice_id` is in the top-k results.
4. Compute **Hit Rate@5** and **MRR@5**.

```python
hits, mrrs = 0, 0
for _, row in ground_truth.iterrows():
    results = vector_search(row["question"], model, db_conn, top_k=5)
    result_ids = [r.invoice_id for r in results]

    if row["source_invoice_id"] in result_ids:
        hits += 1
        rank = result_ids.index(row["source_invoice_id"]) + 1
        mrrs += 1.0 / rank

hit_rate = hits / len(ground_truth)
mrr = mrrs / len(ground_truth)
```

**This is the first real quality checkpoint.** If Hit Rate < 0.7, something is wrong with the serialisation or embedding — debug before continuing.

**Experiment point**: Try `json_to_markdown()` vs `json_to_text()` and compare Hit Rate. Pick the winner.

---

## Phase 4 — LLM Generation (Core RAG Complete)

> **Goal**: Full RAG loop working: question → retrieve → generate answer.

### Step 4.1 — RAG Module

Write `app/rag.py`:

```python
from openai import OpenAI
from app.config import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL

client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)

SYSTEM_PROMPT = """You are InvoiceInsight, an assistant that answers questions about invoices and receipts.
Use ONLY the provided invoice data to answer. If the data does not contain the answer, say "I could not find this in the available invoices."
Be concise and cite the invoice ID in your answer."""

def generate_answer(query: str, retrieved_chunks: list[str]) -> str:
    context = "\n\n---\n\n".join(retrieved_chunks)
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Invoice Data:\n{context}\n\nQuestion: {query}"},
        ],
        max_tokens=512,
        temperature=0,
    )
    return response.choices[0].message.content
```

**Test in notebook**: Ask 5-10 questions, print retrieved context + generated answer. Manual sanity check.

### Step 4.2 — LLM Evaluation (Notebook)

Create `notebooks/eval_llm.ipynb`:

Define 3 prompt variants:

```python
PROMPTS = {
    "concise": "Answer in one sentence. Cite the invoice ID.",
    "detailed": "Answer with full details. Quote exact values. Cite invoice IDs.",
    "structured": "Format: ANSWER: [answer]. SOURCE: [invoice_id]. CONFIDENCE: [high/medium/low]."
}
```

For each prompt variant, run 50 ground-truth questions and use **LLM-as-a-judge**:

```python
JUDGE_PROMPT = """Rate this answer. Score 1-5 (1=wrong, 3=partial, 5=correct).
Question: {question}
Expected: {expected}
Generated: {generated}
Score:"""
```

Compare average scores. Pick the best prompt.

**Experiment point**: This is where you can also test different models (if available) by changing `LLM_MODEL`.

---

## Phase 5 — Streamlit UI

> **Goal**: Working chat interface that a reviewer can interact with.

### Step 5.1 — Chat Page

`streamlit_app.py` (or `app/pages/1_Chat.py`):

- Text input for user question.
- On submit: call `vector_search()` → `generate_answer()`.
- Display: the answer + the retrieved invoice chunks (expandable).
- Thumbs up/down buttons → write to `feedback` table.
- Measure and display response time.

### Step 5.2 — Data Viewer Page

`app/pages/2_Data_Viewer.py`:

- Show all ingested invoices in a table (paginated).
- Click on an invoice to see its JSON and its serialised markdown.
- Simple — just a `SELECT * FROM invoice_chunks` with `st.dataframe()`.

### Step 5.3 — Monitoring Dashboard Page

`app/pages/3_Monitoring.py`:

5 charts, all querying the `feedback` table:

1. **Thumbs Up/Down Ratio** — pie chart.
2. **Queries Per Day** — bar chart.
3. **Average Response Time** — line chart.
4. **Top Retrieved Invoices** — bar chart of most frequently retrieved invoice IDs.
5. **Average Relevance Score** — line chart of cosine similarity over time.

All charts use `st.bar_chart()`, `st.line_chart()`, or `plotly`. Data comes from Postgres — persistent across refreshes.

---

## Phase 6 — Containerisation & Reproducibility

> **Goal**: `docker-compose up` runs the full system. README is complete.

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

### Step 6.2 — Full docker-compose

Add the `app` service (Streamlit) alongside the existing `db` service.

### Step 6.3 — README

- Problem description.
- Architecture diagram (copy from this doc).
- Setup instructions (`docker-compose up`, `.env` config).
- Screenshots of Chat, Data Viewer, Monitoring.
- Rubric self-assessment table (map each rubric item to where it's implemented).
- Pin all dependency versions in `requirements.txt`.

### Step 6.4 — Demo Video

Record a 60-second screencast of the Streamlit app. Embed in README.

---

## Phase 7 — Advanced / Bonus (After Core is Complete)

> These earn bonus points but are NOT required for core functionality.
> Only do these after Phases 1-6 are fully working and committed.

### Step 7.1 — Keyword Search + Hybrid (1 bonus point)

Add `keyword_search()` and `hybrid_search()` to `app/search.py`:

- Keyword: Use the `search_tsv` column (already created in `init.sql`).
- Hybrid: Use Reciprocal Rank Fusion (RRF) to merge vector + keyword results.

**Evaluate in notebook**: Compare Hit Rate / MRR of vector-only vs hybrid.

If hybrid wins, update the Streamlit chat page to use `hybrid_search()` as default.

### Step 7.2 — Re-ranking Evaluation (1 bonus point)

In a notebook only (not in the live app):

- Take top-10 vector results.
- Use the LLM to score each chunk's relevance (0-10) to the query.
- Re-sort by LLM relevance score.
- Compare Hit Rate before and after re-ranking.

No extra models, no extra Docker weight. Just an LLM call.

### Step 7.3 — Query Rewriting (1 bonus point)

Add to `app/rag.py`:

```python
def rewrite_query(original: str) -> str:
    return ask_llm(
        "Rewrite this question to be clearer for searching invoices. Keep it short.",
        f"Original: {original}\nRewritten:"
    )
```

**Evaluate in notebook**: Does rewriting improve Hit Rate? Show before/after comparison.

If it helps, wire it into the Streamlit chat page as an optional toggle.

---

## Development Timeline Summary

| Phase | What | Depends On | Est. Hours |
| :---: | :--- | :--- | :---: |
| 1 | Data + Database | Nothing | 3-4h |
| 2 | Ingestion (serialise + embed + store) | Phase 1 | 2-3h |
| 3 | Retrieval + Evaluation | Phase 2 | 2-3h |
| 4 | LLM Generation + Evaluation | Phase 3 | 2-3h |
| 5 | Streamlit UI (3 pages) | Phase 4 | 3-4h |
| 6 | Docker + README + Video | Phase 5 | 2-3h |
| 7 | Bonus (hybrid, re-rank, rewrite) | Phase 3+ | 3-4h |
| | **Total** | | **~18-24h** |

**Order matters**: Each phase builds on the last. Do not skip ahead to Streamlit (Phase 5) until retrieval evaluation (Phase 3) shows >70% Hit Rate.

---

## Key Principles Throughout

1. **Notebook first, app second.** Every new function is tested in a notebook before being wired into Streamlit.
2. **Config, not code.** LLM provider, embedding model, search parameters — all controlled by env vars or function arguments.
3. **Simple wins.** One invoice = one chunk. No splitting unless an invoice exceeds the embedding model's token limit (~512 tokens ≈ ~2000 characters of markdown).
4. **Ship the data.** `data/invoices.json` and `data/ground_truth.csv` are committed to the repo. Reviewer runs `docker-compose up` and everything works.
5. **Measure before polishing.** Hit Rate and MRR tell you if the core works. If retrieval is broken, no amount of UI polish fixes it.
