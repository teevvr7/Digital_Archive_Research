# Revised RAG Insights: InvoiceInsight Capstone

> Written after re-evaluating the original plan against the user's constraints, available infrastructure, and practical goals.

---

## 1. Context Recap

**What we are building**: A standalone RAG proof-of-concept for LLM-Zoomcamp capstone. It must be:
- Independent repository, simple, easy to clone and review.
- Related to invoices/receipts/purchase orders (relevant to the IDP system).
- A useful R&D sandbox — algorithms and patterns proven here will be ported into DataWiz later.

**What we have available**:
- Self-hosted **Qwen3-VL-4B-Instruct** on Lightning AI (OpenAI-compatible API, already running).
- Lightning AI cloud compute with GPU.
- Existing IDP pipeline that produces structured JSON from documents.
- PostgreSQL (Supabase) with `pgvector` support.

---

## 2. Can Qwen3-VL Be Used for RAG Text Generation?

### Short Answer: Yes, it works. But there are real constraints to manage.

**Why it is acceptable for this project:**
- Qwen3-VL's text generation quality is reported as "on par with pure LLMs" by the Qwen team. It uses early-stage joint pretraining so its language ability is not significantly degraded by the vision module.
- For a **proof-of-concept capstone**, the answer quality will be more than sufficient. You are answering factual questions about structured invoice data (vendor name, total amount, line items) — this is **fact retrieval**, not creative writing. Qwen3-VL handles this well.
- You already have it deployed and running. Zero additional infrastructure cost. Zero additional API keys.

**Constraints to manage:**

| Constraint | Current Value | Impact on RAG | Mitigation |
| :--- | :--- | :--- | :--- |
| `vlm_max_model_len` | 2048 tokens | Very tight. System prompt + retrieved context + user question + answer must ALL fit in 2048. | For the capstone: configure vLLM with a larger `max_model_len` (e.g., 4096 or 8192). Qwen3-VL-4B supports up to 32K tokens natively. The 2048 limit is a vLLM serving constraint, not a model limitation. |
| `vlm_max_output_tokens` | 768 | Fine for short factual answers. | Keep as-is. RAG answers about invoices are typically 50-200 tokens. |
| Inference speed | Slower than pure text models | Acceptable for a demo. Not a dealbreaker. | No action needed for PoC. |

### Critical Action: Increase Context Window for RAG

The **single most important change** is to increase `max_model_len` on the Lightning AI vLLM server for the RAG use case. With 2048 tokens, you can barely fit 2-3 invoice chunks plus the question. With 4096 or 8192, you can comfortably fit 5-8 retrieved chunks, which is the standard for RAG.

**For the capstone project**, you can either:
1. Reconfigure the existing Lightning AI vLLM instance with a higher `max_model_len` (if RAM allows on the GPU).
2. Or run a separate, lightweight vLLM instance on Lightning AI dedicated to the capstone (isolating it from the IDP workload).

> **Recommendation**: Option 1 is simpler. Just change the vLLM launch parameter. Qwen3-VL-4B at 8192 context will use ~6-8 GB VRAM on an A10G or L4 GPU — easily within Lightning AI's free-tier GPU quota.

---

## 3. The JSON Dataset Question — You Are Right, But With Nuance

### Your reasoning is correct:

The flow is:
```
Raw Document → IDP Pipeline → Structured JSON (extracted_data) → Knowledge Base → RAG
```

The RAG operates **downstream of extraction**. By the time RAG runs, the data is already structured JSON. The raw OCR text is irrelevant to the RAG component — it has already done its job during the IDP phase.

Therefore:
- ✅ **JSON as the knowledge base format is correct** for this specific use case.
- ✅ **Retrieval evaluation against JSON ground truth** makes sense — you are checking "did the RAG find the right invoice record?"
- ✅ **LLM generation evaluation** is separate — you are checking "given the correct context, did the LLM produce a correct answer?"

### The nuance: JSON must be serialised to text before embedding

Embedding models (`all-MiniLM-L6-v2`) do not understand raw JSON syntax. Feeding them `{"vendor": "TechCorp", "total": 6480.00}` will produce a poor embedding because the model treats `{`, `"`, `:` as noise tokens.

**The proven technique** (from production RAG systems over structured data) is to **flatten the JSON into natural language** before embedding:

```python
# Raw JSON from IDP extraction
invoice = {
    "vendor": "TechCorp Sdn Bhd",
    "invoice_number": "INV-2026-001",
    "invoice_date": "2026-07-14",
    "line_items": [
        {"description": "Lenovo ThinkPad Laptop", "qty": 5, "unit_price": 1200.00, "amount": 6000.00},
        {"description": "USB-C Docking Station", "qty": 5, "unit_price": 89.00, "amount": 445.00}
    ],
    "subtotal": 6445.00,
    "tax": 515.60,
    "grand_total": 6960.60
}

# Serialise to embeddable text
def json_to_text(inv: dict) -> str:
    lines = [
        f"Invoice {inv.get('invoice_number', 'N/A')} from {inv.get('vendor', 'Unknown')}",
        f"Date: {inv.get('invoice_date', 'N/A')}",
    ]
    for item in inv.get("line_items", []):
        lines.append(
            f"Item: {item['description']}, Qty: {item['qty']}, "
            f"Unit Price: ${item['unit_price']:.2f}, Amount: ${item['amount']:.2f}"
        )
    lines.append(f"Subtotal: ${inv.get('subtotal', 0):.2f}")
    lines.append(f"Tax: ${inv.get('tax', 0):.2f}")
    lines.append(f"Grand Total: ${inv.get('grand_total', 0):.2f}")
    return "\n".join(lines)
```

**Output:**
```
Invoice INV-2026-001 from TechCorp Sdn Bhd
Date: 2026-07-14
Item: Lenovo ThinkPad Laptop, Qty: 5, Unit Price: $1200.00, Amount: $6000.00
Item: USB-C Docking Station, Qty: 5, Unit Price: $89.00, Amount: $445.00
Subtotal: $6445.00
Tax: $515.60
Grand Total: $6960.60
```

This text is what gets embedded and stored. The original JSON is stored alongside it (for display and for ground-truth comparison).

### Chunking Strategy for Invoices

Since each invoice's flattened text is typically **200-600 characters** (well under embedding model limits of ~512 tokens), the simplest and most effective strategy is:

**One invoice = one chunk. No splitting needed.**

This is actually ideal because:
- Each chunk has complete context (vendor + date + all line items + totals).
- Retrieval finds the right invoice, not a fragment of one.
- No risk of cutting a line item in half.

If an invoice has a very long line-item list (30+ items), split into:
- **Chunk A**: Header + first N line items + subtotal/tax/total.
- **Chunk B**: Header (repeated) + remaining line items.

Prepending the header to each chunk ensures the chunk is self-contained.

---

## 4. Revised Architecture (Simplified)

Based on everything discussed, here is the leanest practical architecture:

```
┌──────────────────────────────────────────────────────────┐
│              Streamlit App (single container)             │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  Page 1: Chat (Q&A over invoices)                   │ │
│  │  Page 2: Data Viewer (browse ingested invoices)     │ │
│  │  Page 3: Monitoring Dashboard (5 simple charts)     │ │
│  └──────────────────────────────────────────────────────┘ │
│                         │                                 │
│                    Python modules                         │
│  ┌─────────┐  ┌─────────┐  ┌──────┐  ┌──────────────┐   │
│  │ingest.py│  │search.py│  │rag.py│  │evaluate.py   │   │
│  └────┬────┘  └────┬────┘  └──┬───┘  └──────────────┘   │
│       │            │          │                           │
└───────┼────────────┼──────────┼───────────────────────────┘
        │            │          │
        ▼            ▼          ▼
┌───────────────┐         ┌──────────────────────────┐
│ PostgreSQL    │         │ Qwen3-VL on Lightning AI │
│ + pgvector    │         │ (OpenAI-compatible API)  │
│ (Docker)      │         │ Already deployed         │
└───────────────┘         └──────────────────────────┘
```

**Key decisions:**
- **No FastAPI layer**. Streamlit calls Python functions directly.
- **No minsearch in the live app**. Use it only in evaluation notebooks to compare against pgvector.
- **Qwen3-VL is the LLM**. No need for Gemini/OpenAI API keys for the live app.
- **PostgreSQL in Docker** (local container). Not Supabase — keep the capstone completely self-contained.
- **Evaluation in Jupyter notebooks**. Not in the live app.

---

## 5. Dataset Generation Plan

### Format
Each invoice is stored as a JSON file. The generator script creates 150-200 invoices with realistic variation:

```
data/
├── generate_invoices.py      # Faker-based generator script
├── invoices.json             # All 200 invoices in one JSON array (shipped in repo)
└── ground_truth.csv          # 100 Q&A pairs: question, expected_answer, source_invoice_id
```

### Generator Design
Use Python `Faker` library + custom templates:

```python
import random
from faker import Faker

fake = Faker()

VENDORS = [
    "TechCorp Sdn Bhd", "GlobalSupply Pte Ltd", "OfficeMart Trading",
    "PrintPro Solutions", "CloudNet Services", "FreshFood Distribution",
    # ... 20-30 realistic vendor names
]

PRODUCTS = [
    ("Laptop", 800, 2500), ("Monitor", 200, 800), ("Keyboard", 20, 80),
    ("Office Chair", 100, 500), ("Printer Ink", 15, 60), ("A4 Paper (Box)", 8, 25),
    # ... 30-40 product templates with (name, min_price, max_price)
]

def generate_invoice(idx: int) -> dict:
    vendor = random.choice(VENDORS)
    num_items = random.randint(1, 8)
    line_items = []
    for _ in range(num_items):
        name, lo, hi = random.choice(PRODUCTS)
        qty = random.randint(1, 20)
        price = round(random.uniform(lo, hi), 2)
        line_items.append({
            "description": name,
            "qty": qty,
            "unit_price": price,
            "amount": round(qty * price, 2)
        })
    subtotal = round(sum(i["amount"] for i in line_items), 2)
    tax_rate = random.choice([0.06, 0.08, 0.10])
    tax = round(subtotal * tax_rate, 2)
    return {
        "invoice_id": f"INV-{2025 + idx // 100}-{idx:04d}",
        "vendor": vendor,
        "date": fake.date_between("-1y", "today").isoformat(),
        "buyer": fake.company(),
        "buyer_address": fake.address().replace("\n", ", "),
        "line_items": line_items,
        "subtotal": subtotal,
        "tax_rate": f"{tax_rate*100:.0f}%",
        "tax": tax,
        "grand_total": round(subtotal + tax, 2),
        "currency": random.choice(["MYR", "USD", "SGD"]),
        "payment_terms": random.choice(["Net 30", "Net 60", "Due on Receipt"]),
    }
```

### Ground Truth Q&A Generation
Semi-automated: generate question templates, fill in correct answers from the JSON:

```
question,expected_answer,source_invoice_id
"What is the grand total for invoice INV-2026-0042?","$6,960.60",INV-2026-0042
"Which vendor issued invoice INV-2025-0107?","GlobalSupply Pte Ltd",INV-2025-0107
"How many items were on invoice INV-2026-0003?","5",INV-2026-0003
"What was the unit price of Laptop on invoice INV-2026-0042?","$1,200.00",INV-2026-0042
"List all invoices from TechCorp Sdn Bhd","INV-2026-0042, INV-2025-0088, INV-2026-0101","multiple"
```

Question categories to cover:
1. **Lookup by invoice ID** — "What is the total for INV-X?"
2. **Lookup by vendor** — "Which invoices are from vendor Y?"
3. **Line item queries** — "What was the unit price of Z on invoice X?"
4. **Aggregation** — "How many invoices are from vendor Y?" (tests if RAG retrieves ALL relevant invoices)
5. **Comparison** — "Which invoice has the highest grand total?"

---

## 6. Ingestion Pipeline (Detailed)

```python
# ingest.py — run once to populate the database

def ingest_all():
    """Load invoices from JSON, serialise, embed, store in Postgres."""
    invoices = load_json("data/invoices.json")

    model = SentenceTransformer("all-MiniLM-L6-v2")  # singleton

    for inv in invoices:
        # 1. Serialise JSON to readable text
        text = json_to_text(inv)

        # 2. Compute embedding
        embedding = model.encode(text).tolist()

        # 3. Store in Postgres
        db.execute("""
            INSERT INTO invoice_chunks (invoice_id, content_text, content_json, embedding)
            VALUES (%s, %s, %s, %s)
        """, (inv["invoice_id"], text, json.dumps(inv), embedding))

    db.commit()
    print(f"Ingested {len(invoices)} invoices.")
```

**Database schema (simple):**

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE invoice_chunks (
    id SERIAL PRIMARY KEY,
    invoice_id TEXT NOT NULL,
    content_text TEXT NOT NULL,        -- Flattened human-readable text (for embedding match)
    content_json JSONB NOT NULL,       -- Original structured JSON (for display & evaluation)
    embedding vector(384) NOT NULL     -- all-MiniLM-L6-v2 output
);

CREATE INDEX ON invoice_chunks USING hnsw (embedding vector_cosine_ops);

-- For keyword search (hybrid)
ALTER TABLE invoice_chunks ADD COLUMN search_tsv TSVECTOR
    GENERATED ALWAYS AS (to_tsvector('english', content_text)) STORED;
CREATE INDEX ON invoice_chunks USING gin (search_tsv);

-- Feedback / monitoring table
CREATE TABLE feedback (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    retrieved_ids TEXT[],               -- which invoice_ids were retrieved
    relevance_score REAL,               -- cosine similarity of top result
    response_time_ms INT,
    user_rating INT,                    -- +1 or -1 (thumbs up/down)
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 7. Search & Retrieval (Practical Implementation)

### 7.1 Vector Search
```python
def vector_search(query: str, model, db, limit=5):
    q_vec = model.encode(query).tolist()
    rows = db.execute("""
        SELECT invoice_id, content_text, content_json,
               1 - (embedding <=> %s::vector) AS similarity
        FROM invoice_chunks
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """, (q_vec, q_vec, limit))
    return rows.fetchall()
```

### 7.2 Keyword Search (Postgres FTS)
```python
def keyword_search(query: str, db, limit=5):
    rows = db.execute("""
        SELECT invoice_id, content_text, content_json,
               ts_rank(search_tsv, websearch_to_tsquery('english', %s)) AS rank
        FROM invoice_chunks
        WHERE search_tsv @@ websearch_to_tsquery('english', %s)
        ORDER BY rank DESC
        LIMIT %s
    """, (query, query, limit))
    return rows.fetchall()
```

### 7.3 Hybrid Search (RRF)
```python
def hybrid_search(query: str, model, db, limit=5, k=60):
    vec_results = vector_search(query, model, db, limit=10)
    kw_results = keyword_search(query, db, limit=10)

    scores = {}
    for rank, row in enumerate(vec_results, 1):
        scores[row.invoice_id] = scores.get(row.invoice_id, 0) + 1.0 / (k + rank)
    for rank, row in enumerate(kw_results, 1):
        scores[row.invoice_id] = scores.get(row.invoice_id, 0) + 1.0 / (k + rank)

    # Sort by combined RRF score, return top-k
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
    # Fetch full records for the top results
    ...
```

This is simple, proven, and directly portable to DataWiz.

---

## 8. RAG Generation (Using Qwen3-VL)

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://YOUR-LIGHTNING-AI-ENDPOINT/v1",
    api_key="none"
)

SYSTEM_PROMPT = """You are InvoiceInsight, an assistant that answers questions about invoices.
Use ONLY the provided invoice data to answer. If the data does not contain the answer, say so.
Be concise and precise. Include specific numbers, dates, and names from the data."""

def generate_answer(query: str, context_chunks: list[str]) -> str:
    context = "\n---\n".join(context_chunks)
    response = client.chat.completions.create(
        model="qwen3-vl-4b-instruct",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Invoice Data:\n{context}\n\nQuestion: {query}"}
        ],
        max_tokens=512,
        temperature=0,
    )
    return response.choices[0].message.content
```

### Multiple Prompts for LLM Evaluation (Rubric Requirement)

To satisfy the "evaluate multiple LLM approaches" criterion, test at least **3 prompt variants**:

1. **Concise Prompt**: `"Answer in one sentence using only the data provided."`
2. **Detailed Prompt**: `"Answer with full details. Quote exact values from the invoices. Cite the invoice ID."`
3. **Structured Prompt**: `"Answer in this format: ANSWER: [your answer]. SOURCE: [invoice_id]. CONFIDENCE: [high/medium/low]."`

Compare all three using LLM-as-a-judge in the evaluation notebook.

---

## 9. Evaluation Plan (Notebook-Based)

### 9.1 Retrieval Evaluation (`notebooks/eval_retrieval.ipynb`)

For each of the 100 ground-truth questions:
1. Run the query through vector search, keyword search, and hybrid search.
2. Check if the correct `invoice_id` appears in the top-k results.
3. Compute:
   - **Hit Rate@5**: % of questions where the correct invoice is in the top 5.
   - **MRR@5**: Mean Reciprocal Rank (1/rank of the first correct result).

Compare across:
| Retrieval Method | Hit Rate@5 | MRR@5 |
| :--- | :--- | :--- |
| Vector only | ? | ? |
| Keyword only | ? | ? |
| Hybrid (RRF) | ? | ? |

### 9.2 LLM Evaluation (`notebooks/eval_llm.ipynb`)

For 50 ground-truth questions (with known expected answers):
1. Retrieve context using the best retrieval method (from 9.1).
2. Generate answers using each of the 3 prompt variants.
3. Use **LLM-as-a-judge** (call Qwen3-VL itself, or a different model if available):

```python
JUDGE_PROMPT = """Rate this answer on a scale of 1-5:
Question: {question}
Expected Answer: {expected}
Generated Answer: {generated}
Score (1=wrong, 3=partially correct, 5=fully correct):"""
```

Compare prompt variants by average score.

### 9.3 Re-ranking Evaluation (Bonus — In Notebook Only)

In the notebook, evaluate re-ranking without deploying it in the live app:
1. Take top-10 vector search results.
2. Re-rank using a simple **LLM-based re-ranking**: ask the LLM to score each chunk's relevance to the query (0-10).
3. Compare Hit Rate and MRR before and after re-ranking.

This earns the bonus point without adding any Docker image weight.

### 9.4 Query Rewriting (Bonus — Simple)

```python
def rewrite_query(query: str) -> str:
    response = client.chat.completions.create(
        model="qwen3-vl-4b-instruct",
        messages=[{"role": "user", "content":
            f"Rewrite this question to be clearer for searching an invoice database. "
            f"Keep it short.\nOriginal: {query}\nRewritten:"}],
        max_tokens=100, temperature=0
    )
    return response.choices[0].message.content
```

Evaluate: does query rewriting improve Hit Rate? Show results in the notebook.

---

## 10. Monitoring (Simple & Persistent)

Every RAG query writes a row to the `feedback` table (see schema in Section 6).

### Streamlit Monitoring Page — 5 Charts:

1. **Thumbs Up/Down Ratio** — simple pie chart from `user_rating` column.
2. **Average Response Time** — line chart of `response_time_ms` over time.
3. **Number of Queries Per Day** — bar chart from `created_at` grouped by date.
4. **Top Retrieved Invoices** — bar chart of most frequently retrieved `invoice_id` values.
5. **Average Relevance Score** — line chart of `relevance_score` (cosine similarity of the top retrieved chunk) over time.

All charts query the `feedback` table directly. Data persists across refreshes because it is in Postgres.

---

## 11. Containerization

```yaml
# docker-compose.yml
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

  app:
    build: .
    ports:
      - "8501:8501"
    environment:
      DATABASE_URL: postgresql://postgres:postgres@db:5432/invoice_insight
      LLM_BASE_URL: https://YOUR-LIGHTNING-AI-ENDPOINT/v1
      LLM_API_KEY: none
      LLM_MODEL: qwen3-vl-4b-instruct
    depends_on:
      - db

volumes:
  pgdata:
```

```dockerfile
# Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Pre-download embedding model during build (no network needed at runtime)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
COPY . .
CMD ["streamlit", "run", "app/streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

**Note**: The LLM (Qwen3-VL) runs on Lightning AI, not in Docker. This is intentional — GPU workloads should stay on GPU infrastructure. The Docker setup only needs CPU for the app + Postgres.

---

## 12. Revised Repo Structure

```
invoice-insight/
├── README.md                        # Full docs, screenshots, rubric mapping, video link
├── docker-compose.yml
├── Dockerfile
├── init.sql                         # DB schema (tables + indexes)
├── requirements.txt                 # Pinned versions
├── .env.example                     # LLM_BASE_URL, LLM_MODEL, DATABASE_URL
│
├── data/
│   ├── generate_invoices.py         # Faker script to create synthetic invoices
│   ├── generate_ground_truth.py     # Script to create Q&A pairs from invoices
│   ├── invoices.json                # Pre-generated (shipped in repo)
│   └── ground_truth.csv            # Pre-generated (shipped in repo)
│
├── app/
│   ├── streamlit_app.py             # Main entry (multi-page Streamlit)
│   ├── pages/
│   │   ├── 1_Chat.py               # Q&A interface
│   │   ├── 2_Data_Viewer.py        # Browse ingested invoices
│   │   └── 3_Monitoring.py         # 5 charts dashboard
│   ├── ingest.py                    # Chunk + embed + insert into Postgres
│   ├── search.py                    # Vector, keyword, hybrid (RRF)
│   ├── rag.py                       # Retrieve + prompt + call Qwen3-VL
│   ├── db.py                        # Postgres connection helper
│   └── config.py                    # Settings from env vars
│
└── notebooks/
    ├── eval_retrieval.ipynb          # Compare vector vs keyword vs hybrid
    ├── eval_llm.ipynb                # Compare 3 prompt variants (LLM-as-judge)
    └── eval_bonus.ipynb              # Re-ranking + query rewriting evaluation
```

---

## 13. Development Sequence (Practical Order)

| Step | What | Where | Time Estimate |
| :---: | :--- | :--- | :--- |
| 1 | Write `generate_invoices.py` + `generate_ground_truth.py`. Run them. Commit data. | Local Python | 2-3 hours |
| 2 | Write `init.sql` (schema). Test with `docker-compose up db`. | Docker + psql | 30 min |
| 3 | Write `ingest.py`. Run ingestion. Verify data in DB. | Local Python / Notebook | 1-2 hours |
| 4 | Write `search.py` (vector, keyword, hybrid). Test in a notebook. | Notebook | 2-3 hours |
| 5 | Run `eval_retrieval.ipynb`. Compare methods. Pick the best. | Notebook | 1-2 hours |
| 6 | Write `rag.py`. Connect to Qwen3-VL on Lightning AI. Test in notebook. | Notebook | 1-2 hours |
| 7 | Write 3 prompt variants. Run `eval_llm.ipynb`. Compare. | Notebook | 2-3 hours |
| 8 | Run `eval_bonus.ipynb` (re-ranking + query rewriting). | Notebook | 1-2 hours |
| 9 | Build Streamlit UI (Chat page, Data Viewer, Monitoring). | Streamlit | 3-4 hours |
| 10 | Write `Dockerfile`, `docker-compose.yml`. Test full stack. | Docker | 1-2 hours |
| 11 | Write `README.md`. Add screenshots. Record demo video. | Docs | 2-3 hours |

**Total: ~18-27 hours of focused work.**

Start with Steps 1-5 (data + retrieval evaluation) — this is the core R&D that feeds back into DataWiz. The Streamlit UI (Step 9) is polish that can be done last.

---

## 14. Capstone Score Projection

| Rubric Item | Max | Projected Score | Notes |
| :--- | :---: | :---: | :--- |
| Problem description | 2 | 2 | Well-described in README |
| Retrieval flow (KB + LLM) | 2 | 2 | pgvector + Qwen3-VL |
| Retrieval evaluation | 2 | 2 | Vector vs keyword vs hybrid in notebook |
| LLM evaluation | 2 | 2 | 3 prompt variants, LLM-as-judge |
| Interface | 2 | 2 | Streamlit multi-page app |
| Ingestion pipeline | 2 | 2 | Automated Python script |
| Monitoring | 2 | 2 | Feedback table + 5 Postgres-backed charts |
| Containerization | 2 | 2 | Full docker-compose (app + db) |
| Reproducibility | 2 | 2 | Pinned deps, shipped data, clear README |
| **Base Total** | **18** | **18** | |
| Hybrid search (bonus) | 1 | 1 | RRF implemented and evaluated |
| Re-ranking (bonus) | 1 | 1 | LLM-based re-ranking evaluated in notebook |
| Query rewriting (bonus) | 1 | 1 | Simple rewrite step evaluated in notebook |
| **Bonus Total** | **3** | **3** | |
| **Grand Total** | **21** | **21** | |

---

## 15. What Feeds Back into DataWiz

After the capstone is done, the following can be directly ported:

| Capstone Module | DataWiz Integration Point |
| :--- | :--- |
| `json_to_text()` serialiser | `app/modules/idp/rag/chunker.py` — converts `extracted_data` JSON to embeddable text |
| `search.py` (vector + hybrid + RRF) | `app/modules/search/service.py` — adds vector search alongside existing FTS |
| `init.sql` (pgvector schema) | Alembic migration `0012_rag_chatbot.py` + RLS policies |
| `rag.py` (prompt template) | `app/modules/rag/service.py` — tenant-scoped RAG endpoint |
| Evaluation results | Documented confidence in chosen retrieval strategy and prompt template |
| Monitoring schema | `feedback` / `chat_logs` table with tenant_id for multi-tenant isolation |
