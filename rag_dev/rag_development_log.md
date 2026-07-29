# InvoiceInsight RAG Sandbox — Development Log

> This log tracks our architectural decisions, progress across each development phase, implementation details, and key RAG concepts. It acts as both a system design log and a study reference for the RAG architecture.

---

## Workspace Structure (Modular Layout)
For clean modularity, standard Capstone presentation, and import safety, the application is organized with source code nested inside the `src/` directory while the entrypoints (Streamlit GUI launcher and notebook scripts) reside in the root:

```
rag_dev/ (Project Root)
├── .env                  # Configuration variables
├── .env.example          # Template for configurations
├── requirements.txt      # Python dependencies
├── docker-compose.yml    # Database container orchestration
├── init.sql              # Database schema and index initialization
│
├── streamlit_app.py      # App entrypoint (Root)
├── 01_foundations.py     # Setup notebook script (Root)
│
├── data/
│   ├── invoices.json     # Generated dataset (200 records)
│   └── ground_truth.csv  # Evaluation questions (150 rows)
│
└── src/                  # Core application source code
    ├── config.py         # dotenv loader
    ├── db.py             # psycopg3 connection client
    ├── serialise.py      # JSON-to-Markdown converter
    ├── ingest.py         # Embedding / Ingestion processor
    ├── search.py         # Vector / keyword / hybrid retrieval
    └── rag.py            # Prompt building & LLM client interface
```

---

## Phase 1: Foundations (Completed)

**Goal**: Establish the dataset, define standard evaluation questions, and set up a local Postgres database with vector search capabilities.

### 1. What was Implemented
* **Scaffolding**: Created the flat python file layout and pinned versions in `requirements.txt`.
* **Synthetic Data (`data/invoices.json`)**: Generated 200 diverse mock invoice objects using `Faker`. Each invoice has dynamic dates, payment terms, buyer details, subtotal/tax, currency codes (USD, SGD, MYR), and a list of structured line items (Laptop, UPS units, etc.).
* **Ground-Truth CSV (`data/ground_truth.csv`)**: Extracted 150 matching Q&A pairs covering lookup queries (vendors, dates, subtotals, grand totals), nested properties (unit prices/quantities of specific items), and multi-document count aggregations.
* **Database Setup**:
  * Launched a local Docker container running PostgreSQL 16 with the native **`pgvector`** extension enabled.
  * Initialized the schemas and GIN/HNSW indexes defined in `init.sql`.

---

### 2. Core Concepts & "Behind-the-Scenes" Highlights

#### Why Psycopg 3 instead of Psycopg 2?
Our main project environment uses **Psycopg 3** (imported as `import psycopg`).
* Psycopg 3 is a complete, modern rewrite of the standard PostgreSQL driver for Python.
* In Psycopg 2, fetching dictionary rows required importing a separate cursor class (`from psycopg2.extras import DictCursor`).
* In Psycopg 3, row formatters are cleaner. We pass a `row_factory` directly to the connection object:
  ```python
  import psycopg
  from psycopg.rows import dict_row

  conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
  ```
  This automatically transforms all fetch results from standard tuples (`("INV-001", "Acme", ...)`) into native Python dictionaries (`{"invoice_id": "INV-001", "vendor": "Acme", ...}`) across all query outputs.

#### The "KeyError: 0" Bug
When testing the database connection in `01_foundations.py`, we executed `SELECT version();` and called `cur.fetchone()[0]`. Because `row_factory=dict_row` was enabled, the database returned `{"version": "PostgreSQL 16..."}` rather than a tuple. Accessing index `0` threw a `KeyError: 0`. We fixed it by using a type-checked resolution:
```python
row = cur.fetchone()
db_version = list(row.values())[0] if isinstance(row, dict) else row[0]
```

#### Windows Encoding Trap
When printing logs, using the checkmark emoji (`✅`) caused a `UnicodeEncodeError: 'charmap' codec can't encode character '\u2705'` on Windows. Windows terminals default to `cp1252` encoding instead of `UTF-8`. Emojis must be replaced with ASCII equivalents (like `[OK]`) in command line logs to prevent system execution crashes.

---

### 3. Key RAG Strategy: JSON-to-Markdown Serialisation
Before embedding structured JSON data into a vector space, it must be serialised into natural text. In [serialise.py](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/rag_dev/serialise.py), we implemented `json_to_markdown()`. 

#### Comparison of Serialisation Formats:
* **Option 1: Flat Key-Value Plain Text**:
  ```text
  invoice_id: INV-2025-0001
  vendor: Summit Hardware
  line_items: [{'description': 'Laptop', 'qty': 12, 'unit_price': 1267.55, 'amount': 15210.6}]
  total: 16123.24
  ```
  *Criticism*: Embedding models often treat brackets (`[`), syntax quotes (`'`), and raw lists as structural noise. Key-value structures lose formatting context, which makes semantic lookup harder.
  
* **Option 2: Structured Markdown (Implemented & Chosen)**:
  ```markdown
  # Invoice INV-2025-0001
  - **Invoice Id**: INV-2025-0001
  - **Vendor**: Summit Hardware
  ## Line Items
  1. **Description**: Laptop | **Qty**: 12 | **Unit Price**: 1267.55 | **Amount**: 15210.6
  - **Grand Total**: 16123.24
  ```
  *Strength*: Markdown retains clear hierarchical headings (`#`, `##`), bullet points, and clean separators (`|`) for arrays of objects. Embedding models are trained extensively on markdown-rich codebases (like GitHub), so they understand markdown blocks significantly better than raw serialised JSON dictionaries.

---

### 4. Verification Checkpoint
Run the script to verify the foundations output:
```powershell
python 01_foundations.py
```

**Expected Log Output**:
```text
--- Configurations Loaded ---
Database URL: postgresql://postgres:postgres@localhost:5432/invoice_insight
Model Name:   qwen3-vl-4b-instruct
Data Dir:     data
Generated 200 invoices saved to 'data\invoices.json'
Generated 150 ground-truth rows saved to 'data\ground_truth.csv'
Connected successfully to PostgreSQL: PostgreSQL 16.14 ...
pgvector extension verified: Enabled (OK)
=== OPTION 1: Serialised to Markdown (Recommended) ===
...
```

---

---

## Phase 2: Ingestion & Embeddings (Completed)

**Goal**: Implement the embedding loop to load local models, vectorize the markdown texts, and write them to the Postgres vector space.

### 1. What was Implemented
* **Ingestion Worker (`src/ingest.py`)**: Built `ingest_invoices()` using `SentenceTransformer("all-MiniLM-L6-v2")`.
* **Dense Embeddings**: Serialised each JSON invoice into Markdown format, computed a 384-dimensional dense floating-point vector, and stored the result in `invoice_chunks`.
* **Database Upsert**: Used `ON CONFLICT (invoice_id) DO UPDATE` so re-ingesting or updating formatting automatically updates database records without primary key errors.
* **Verification Script (`02_ingestion.py`)**: Embedded and saved all 200 invoices, verifying `vector(384)` dimensions and data integrity.

---

## Phase 3: Retrieval & Evaluation (Benchmark Completed)

**Goal**: Given a user query, retrieve the top-K relevant document chunks and benchmark search accuracy across vector, keyword, and hybrid algorithms over 149 test queries.

### 1. Benchmark Execution Results

```text
=== RETRIEVAL EVALUATION RESULTS ===
             Algorithm  Total Queries  Hits  Hit Rate @ 5 (%)  MRR @ 5
Vector Search (Cosine)            149     7              4.70   0.0234
  Keyword Search (FTS)            149    72             48.32   0.4832
   Hybrid Search (RRF)            149    77             51.68   0.3173
```

---

### 2. Critical Analysis of Findings

1. **Vector Search Disastrous Failure (Hit Rate: 4.70%, MRR: 0.0234)**:
   * *Root Cause*: Text embedding models (`all-MiniLM-L6-v2`) capture semantic ideas (e.g., *"billing date"*), but are **completely blind to exact alphanumeric IDs** (e.g., `INV-2026-0145`). 
   * To an embedding model, `INV-2026-0145` and `INV-2025-0071` have nearly identical vector representations (~99% cosine similarity). The model simply retrieves random invoices containing billing dates, resulting in a 4.7% hit rate by pure chance.
   * *Takeaway*: Pure dense vector search fails on structured document datasets dominated by unique IDs or code queries.

2. **Keyword Search (FTS) Performance (Hit Rate: 48.32%, MRR: 0.4832)**:
   * *Root Cause*: PostgreSQL `tsvector` performs exact token matching. When an invoice ID is present in the query, FTS matches the exact document and ranks it **#1** (hence MRR = 0.4832 matches Hit Rate 48.32%).
   * *Limitation*: Capped at ~48% because PostgreSQL's `english` text search dictionary splits hyphenated strings (`INV-2026-0145` → `inv`, `2026`, `0145`), causing misses when query formatting or punctuation varies.

3. **Hybrid Search (RRF) Trade-off (Hit Rate: 51.68%, MRR: 0.3173)**:
   * *Hit Rate Boost*: Combining Vector + Keyword captured additional queries that missed under pure keyword search.
   * *MRR Drop (0.4832 → 0.3173)*: Standard RRF sums equal weights $\frac{1}{60 + \text{rank}}$. Because all 200 invoices have high semantic similarity (~0.60) to generic phrases like *"billing date"*, noisy candidate invoices received high vector ranks (1, 2, 3). In RRF, these noisy vector ranks tied or beat exact keyword hits, pushing the correct invoice down from Rank 1 to Rank 2, 3, or 4.

---

### 3. Proposed Solutions for Next Phase Iteration

1. **Weighted Reciprocal Rank Fusion (Weighted RRF)**:
   * Give Keyword ranks 2x weight over Vector ranks to prevent noisy vector candidates from pushing exact keyword hits down:
     $$\text{RRF Score} = \frac{1.0}{60 + \text{rank}_{\text{vector}}} + \frac{2.0}{60 + \text{rank}_{\text{keyword}}}$$
2. **Explicit Regex ID Extraction & Metadata Filtering**:
   * Pre-parse queries for regex patterns like `INV-\d{4}-\d{4}`. If an exact ID is detected, execute a high-priority exact filter lookup before falling back to hybrid retrieval.
3. **Query Expansion / Serialisation Enrichment**:
   * Include un-hyphenated invoice IDs (`INV20260145`) inside the markdown `content_text` block during ingestion to ensure FTS never misses an ID token.

---

## Phase 3B: Retrieval Improvements (Experiments Completed)

**Goal**: Improve Hit Rate and MRR before moving to LLM generation.

### Experiment 1: FTS Tokenization Fix (`simple` dictionary) — ❌ FAILED

**Hypothesis**: Switching PostgreSQL's `tsvector` dictionary from `'english'` to `'simple'` would preserve hyphenated invoice IDs as intact tokens, improving keyword matching.

**Result**: Keyword Search dropped from 48.32% → **0.00%** Hit Rate.

**Why it failed**: The `simple` dictionary does not remove stopwords. A query like *"What is the billing date for invoice INV-2026-0145?"* becomes `'what' & 'is' & 'the' & 'billing' & 'date' & 'for' & ...` — all tokens required via AND. The invoice markdown text does not contain `"what"`, `"is"`, `"the"`, or `"for"`, so zero documents match.

**Key learning**: Hyphen splitting is a **parser-level** behavior in PostgreSQL, not a dictionary-level one. `INV-2026-0145` gets split into `inv`, `2026`, `0145` by the parser regardless of dictionary. The dictionary only controls stemming and stopword removal. This approach was fundamentally flawed.

**Action**: Reverted to `'english'` dictionary. The hyphen/ID problem is now delegated to the Phase 4 query router (direct SQL lookup bypasses FTS entirely).

### Experiment 2: Weighted RRF (2.5x keyword weight) — ✅ SUCCESS

**Change**: In `hybrid_search()`, keyword ranks now receive 2.5x weight:
```
RRF Score = (1.0 / (60 + rank_vector)) + (2.5 / (60 + rank_keyword))
```

**Before vs After comparison**:

```text
=== BASELINE (Phase 3 — Equal-Weight RRF) ===
             Algorithm  Hit Rate @ 5 (%)  MRR @ 5
Vector Search (Cosine)              4.70   0.0234
  Keyword Search (FTS)             48.32   0.4832
   Hybrid Search (RRF)             51.68   0.3173

=== PHASE 3B (Weighted RRF, keyword_weight=2.5) ===
             Algorithm  Hit Rate @ 5 (%)  MRR @ 5
Vector Search (Cosine)              4.70   0.0234
  Keyword Search (FTS)             48.32   0.4832
   Hybrid Search (RRF)             51.68   0.4985
```

**Analysis**:
- **Hit Rate unchanged (51.68%)**: Same documents are found — weighting affects rank order, not which documents appear in top-5.
- **MRR improved: 0.3173 → 0.4985 (+57%)**: Exact keyword matches now consistently rank at position #1 instead of being displaced by semantically similar but wrong vector candidates. This means when the correct document is found, it is almost always the top result.

### Phase 3B Conclusion

The retrieval pipeline is now at its practical ceiling for the current architecture (51.68% Hit Rate, 0.4985 MRR). The remaining ~48% of missed queries fail because PostgreSQL FTS tokenizes hyphenated invoice IDs into fragments. This limitation is by design — it will be solved by the **Phase 4 query router**, which routes ID-containing queries to direct SQL lookup (bypassing FTS entirely).

## Architecture Pivot: From Pure RAG to Hybrid (Text-to-SQL + RAG)

### The Realisation

After analyzing the Phase 3 benchmark results, we identified a fundamental mismatch between the data shape and the retrieval approach:

**Our data is structured** (JSON with typed fields: `invoice_id`, `vendor`, `date`, `subtotal`, `grand_total`, `line_items[]`). **Real SME user queries are structured operations** — aggregations, filters, and lookups — not semantic searches.

Consider what real business users actually ask:

| Query Type | Example | Correct Tool |
|---|---|---|
| Aggregation | "Total sales of Laptops last month" | SQL (`SUM`, `WHERE`, `GROUP BY`) |
| Filtering | "Show all invoices from Summit Hardware" | SQL (`WHERE vendor = ...`) |
| Date range | "What invoices were issued in March 2026?" | SQL (`WHERE date BETWEEN ...`) |
| Fuzzy / contextual | "I bought equipment from a hardware store around March" | RAG (semantic similarity) |

**Critical insight**: RAG retrieves **top-K documents** (e.g., 5 out of 200). Aggregation queries require scanning **all** documents. No amount of vector search or hybrid retrieval improvement will make a top-5 retrieval answer "total sales of Laptops" correctly — it will always miss the other 195 invoices.

### The Decision

We pivoted from a pure RAG architecture to a **lightweight hybrid system** with a rule-based query router:

```
User Query → Router (deterministic if/else, ~20 lines of Python)
                ├── Structured query → LLM generates SQL → Execute → Format answer
                └── Fuzzy query      → RAG (embed → retrieve → LLM generate)
```

**This is NOT an agent.** An agent autonomously decides tools and chains multi-step reasoning. Our router is a deterministic classifier — simple, predictable, debuggable. The capstone rubric allows *"a combination of both"* (RAG + structured query), which this fully satisfies.

### Why This Architecture is Stronger for the Capstone

1. **Evidence-driven**: The pivot is backed by real benchmark data (4.70% vector Hit Rate), not assumptions. Documenting this journey demonstrates genuine R&D thinking.
2. **Covers all real query types**: Aggregation, filtering, ID lookup (via SQL) + fuzzy, contextual (via RAG).
3. **Simple to implement**: The router is ~20 lines. Text-to-SQL is one LLM prompt. RAG is already built.
4. **Rubric coverage**: We now evaluate 4+ retrieval approaches (vector, FTS, hybrid RRF, Text-to-SQL), exceeding the rubric requirement of "multiple retrieval approaches evaluated."

### Reference

Full revised roadmap: [`rag_roadmap_v2.md`](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/rag_dev/rag_roadmap_v2.md)
Brainstorm ideation notes: [`retrieval_improvement_brainstorm.md`](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/rag_dev/retrieval_improvement_brainstorm.md)

---

## LLM Provider Strategy

### Design Principle: Provider-Agnostic via OpenAI-Compatible API

All LLM calls in this project use the standard **OpenAI Python client** (`from openai import OpenAI`). The provider is controlled entirely by 3 environment variables in `.env`:

```env
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=gsk-...
LLM_MODEL=llama-3.3-70b-versatile
```

To swap providers, change `.env` values only. **Zero code changes required.**

| Provider | `LLM_BASE_URL` | `LLM_MODEL` (examples) |
|---|---|---|
| **Groq** (current default) | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile`, `gemma2-9b-it` |
| Self-hosted Qwen3-VL | `https://YOUR-LIGHTNING.../v1` | `qwen3-vl-4b-instruct` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini`, `gpt-4o` |
| Ollama (local) | `http://localhost:11434/v1` | `llama3.2`, `qwen2.5:7b` |
| Together AI | `https://api.together.xyz/v1` | `meta-llama/Llama-3.3-70B-Instruct-Turbo` |

### Why Groq for This Project

* **Free tier**: Generous rate limits for development and evaluation.
* **Speed**: Groq's LPU inference is extremely fast (~500 tokens/sec), ideal for batch evaluation runs.
* **Quality**: Access to `llama-3.3-70b-versatile` — a strong model for both Text-to-SQL generation and RAG answer synthesis.
* **Swappable**: If Groq rate limits are hit during evaluation, switch to Ollama (local, unlimited) by changing one line in `.env`.

---

## Ground Truth Expansion (Planned)

The current `data/ground_truth.csv` contains 150 questions that are predominantly **single-document ID lookups** (e.g., "What is the billing date for invoice INV-2026-0145?"). These questions heavily favor keyword search and are inherently unsuitable for pure vector search.

For the revised hybrid architecture, we need to expand the ground truth to cover both paths:

| Category | Example Question | Expected Path | Count (Target) |
|---|---|---|:---:|
| ID lookup | "What is the total for INV-2026-0145?" | SQL (direct) | Keep existing ~100 |
| Aggregation | "Total amount spent on Laptops across all invoices" | SQL (aggregate) | Add ~15 |
| Vendor filter | "List all invoices from Summit Hardware" | SQL (filter) | Add ~10 |
| Date range | "What invoices were issued in March 2026?" | SQL (filter) | Add ~10 |
| Fuzzy / contextual | "I ordered some cleaning supplies, can you find which invoice?" | RAG (semantic) | Add ~15 |

This expansion ensures that both the SQL path and the RAG path are properly evaluated with appropriate test cases.

