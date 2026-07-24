# RAG Retrieval Improvement Brainstorm

> Experiment ideas ranked by implementation speed. Generated from Phase 3 benchmark failure analysis (Vector: 4.70%, FTS: 48.32%, Hybrid RRF: 51.68% Hit Rate@5).

---

## The Core Problem

Our data is **structured** (JSON with typed fields: `invoice_id`, `vendor`, `date`, `subtotal`, `grand_total`, `line_items[]`). Our queries are **structured lookups** (give me field X of document Y). But our retrieval treats everything as **unstructured text** — flattening rich JSON into markdown soup, then hoping a semantic embedding or keyword tokenizer can fish out the right document.

This is a fundamental mismatch: **we are using a search engine where we need a database query engine**.

---

## How SME Business Users Actually Ask Questions

Before proposing solutions, consider the realistic query landscape:

| Category | Example Questions | What the system actually needs to do |
|---|---|---|
| **Single-doc ID lookup** | "What is the total for INV-2026-0145?" | Filter by exact ID → read one field |
| **Vendor filter** | "Show all invoices from Summit Hardware" | Filter by vendor → return list |
| **Date range** | "What invoices were issued in March 2026?" | Filter by date range → return list |
| **Aggregation** | "What is the total amount spent on Laptops?" | Scan all line_items → SUM |
| **Comparison** | "Which vendor has the highest total billing?" | GROUP BY vendor → ORDER BY SUM |
| **Fuzzy / conversational** | "Were there any large orders recently?" | Semantic understanding → filter + sort |
| **Multi-hop** | "What did we buy from the vendor who issued INV-2025-0033?" | Resolve vendor from doc → filter by vendor |

**Key insight**: Categories 1–5 (the vast majority of real SME usage) are essentially **SQL queries**, not semantic search problems. Only categories 6–7 benefit from embeddings.

---

## Ranked Ideas (Fastest to Implement First)

---

### Idea 1: Direct JSON Field Lookup (SQL Bypass)
**Effort**: ~30 minutes | **Expected Impact**: 95%+ Hit Rate on ID-specific queries

Instead of searching through embeddings or text tokens, query the `content_json` JSONB column directly using PostgreSQL's native JSON operators.

**How it works**:
```python
# Extract invoice ID from query via regex
import re
match = re.search(r'INV-\d{4}-\d{4}', query, re.IGNORECASE)
if match:
    cursor.execute(
        "SELECT * FROM invoice_chunks WHERE content_json->>'invoice_id' = %s",
        (match.group(0).upper(),)
    )
```

**Why this is powerful**: We already store the full raw JSON in `content_json JSONB`. PostgreSQL can query inside JSONB natively. No embedding model needed. Instant, exact, deterministic.

**What it solves**: All `date_lookup`, `vendor_lookup`, `subtotal_lookup`, `total_lookup`, `line_item_price`, `line_item_qty` queries that mention an invoice ID.

**What it does NOT solve**: Fuzzy queries without an explicit ID, aggregation queries across multiple documents.

---

### Idea 2: Query Intent Router (Classification Layer)
**Effort**: ~1 hour | **Expected Impact**: Routes each query to its optimal handler

Add a lightweight classification step before retrieval that inspects the query and routes it to the best handler.

**How it works**:
```python
def classify_query(query: str) -> str:
    # Rule-based classification (fast, no LLM needed)
    if re.search(r'INV-\d{4}-\d{4}', query, re.IGNORECASE):
        return "id_lookup"          # → Direct JSON/SQL lookup
    if any(w in query.lower() for w in ["how many invoices", "total spent", "count"]):
        return "aggregation"        # → SQL aggregation query
    if any(w in query.lower() for w in ["all invoices from", "show me"]):
        return "filter"             # → SQL WHERE clause
    return "semantic"               # → Hybrid vector+keyword search (fallback)
```

**Architecture**:
```
User Query → classify_query() → Router
                                   ├── "id_lookup"    → Idea 1 (Direct JSONB lookup)
                                   ├── "aggregation"  → Idea 3 (Text-to-SQL)
                                   ├── "filter"       → Idea 3 (Text-to-SQL)
                                   └── "semantic"     → Existing hybrid_search()
```

**Why this matters**: No single retrieval method works for all query types. Routing is the simplest way to combine multiple strategies without changing any individual one.

---

### Idea 3: Text-to-SQL Generation (LLM Writes the Query)
**Effort**: ~2 hours | **Expected Impact**: Handles aggregation/filter/comparison queries perfectly

Instead of retrieving text chunks and hoping the LLM reads them correctly, have the LLM **generate a SQL query** against the structured data.

**How it works**:
1. Feed the LLM the table schema (just field names and types, not data).
2. The LLM generates a SQL SELECT query.
3. Execute the SQL against Postgres.
4. Return the result to the user.

**Prompt template**:
```
You are a SQL assistant. Given the following JSON schema for invoice documents
stored in the `invoice_chunks` table (column: content_json JSONB):

Fields: invoice_id, vendor, date, buyer, buyer_address, subtotal, tax_rate,
tax, grand_total, currency, payment_terms, line_items[].description,
line_items[].qty, line_items[].unit_price, line_items[].amount

Write a PostgreSQL query to answer: "{user_question}"
Use content_json->> operators for field access.
```

**What it handles well**: Aggregations ("total spent on Laptops"), comparisons ("highest invoice"), date filters, multi-field joins — all queries that are impossible for standard RAG.

**Risk**: SQL injection (mitigated by read-only DB user), hallucinated column names (mitigated by schema validation).

---

### Idea 4: Weighted RRF with Keyword Priority
**Effort**: ~15 minutes | **Expected Impact**: MRR improvement from 0.31 → ~0.45+

The simplest code change. Give keyword search ranks 2–3x the weight of vector ranks in the RRF score formula.

**Change in `hybrid_search()`**:
```python
# Before (equal weights):
rrf_scores[inv_id]["score"] += 1.0 / (k + rank)

# After (keyword-weighted):
# For vector ranks:
rrf_scores[inv_id]["score"] += 1.0 / (k + rank)  # weight = 1.0
# For keyword ranks:
rrf_scores[inv_id]["score"] += 2.5 / (k + rank)  # weight = 2.5
```

**Why**: For structured data with IDs, an exact keyword match is almost always the correct document. Semantic similarity is noise. Weighting keyword higher prevents noisy vector candidates from displacing exact matches.

**Limitation**: Still fails if the keyword search itself misses the document (the ~52% cap from FTS tokenization issues).

---

### Idea 5: Structured Metadata Columns + Pre-Filtering
**Effort**: ~1.5 hours | **Expected Impact**: Enables SQL-grade filtering before vector search

Add explicit indexed columns for key structured fields, extracted from `content_json` at ingestion time.

**Schema change (add to `init.sql`)**:
```sql
ALTER TABLE invoice_chunks ADD COLUMN vendor TEXT 
    GENERATED ALWAYS AS (content_json->>'vendor') STORED;
ALTER TABLE invoice_chunks ADD COLUMN invoice_date DATE 
    GENERATED ALWAYS AS ((content_json->>'date')::date) STORED;
ALTER TABLE invoice_chunks ADD COLUMN grand_total NUMERIC 
    GENERATED ALWAYS AS ((content_json->>'grand_total')::numeric) STORED;
ALTER TABLE invoice_chunks ADD COLUMN currency TEXT 
    GENERATED ALWAYS AS (content_json->>'currency') STORED;

CREATE INDEX idx_vendor ON invoice_chunks(vendor);
CREATE INDEX idx_date ON invoice_chunks(invoice_date);
```

**How it improves retrieval**: Before running vector search, pre-filter the candidate set:
```python
# "What did we buy from Summit Hardware in March?"
cursor.execute("""
    SELECT ... FROM invoice_chunks
    WHERE vendor = 'Summit Hardware'
      AND invoice_date BETWEEN '2026-03-01' AND '2026-03-31'
    ORDER BY embedding <=> %s::vector
    LIMIT 5;
""", (q_vec,))
```

**Why**: Vector search on 200 docs where 195 are irrelevant produces noise. Pre-filtering down to 5–10 relevant candidates makes vector ranking meaningful.

---

### Idea 6: Smarter FTS Tokenization (Fix the 48% Cap)
**Effort**: ~45 minutes | **Expected Impact**: Keyword search jumps from 48% → 80%+ Hit Rate

The reason keyword search caps at 48% is that PostgreSQL's `english` dictionary splits `INV-2026-0145` into separate tokens (`inv`, `2026`, `0145`). When `plainto_tsquery` processes the query, it may not recombine them correctly.

**Fix A — Use `simple` dictionary instead of `english`**:
```sql
-- In init.sql, change the tsvector config:
ALTER TABLE invoice_chunks ADD COLUMN search_tsv TSVECTOR
    GENERATED ALWAYS AS (to_tsvector('simple', content_text)) STORED;
```
The `simple` dictionary does not apply stemming or stopword removal, preserving hyphenated tokens intact.

**Fix B — Use `phraseto_tsquery` instead of `plainto_tsquery`**:
```python
# In keyword_search():
cursor.execute("""
    WHERE search_tsv @@ phraseto_tsquery('simple', %s)
""", (query,))
```
This forces phrase-level proximity matching, requiring tokens to appear adjacent and in order.

**Fix C — Add un-hyphenated ID variant to content_text during ingestion**:
```python
# In ingest.py, append to markdown text:
text_content += f"\nAlternate ID: {invoice_id.replace('-', '')}"
# So "INV20260145" also exists as a searchable token
```

---

### Idea 7: Agentic RAG (LLM Decides the Tool)
**Effort**: ~3 hours | **Expected Impact**: Handles every query type, including multi-hop

Instead of a rule-based router (Idea 2), let the LLM itself decide which "tool" to call. This is the ReAct / function-calling pattern.

**How it works**:
```python
tools = [
    {"name": "lookup_invoice", "description": "Get a specific invoice by ID",
     "parameters": {"invoice_id": "string"}},
    {"name": "search_invoices", "description": "Search invoices by semantic query",
     "parameters": {"query": "string"}},
    {"name": "run_sql", "description": "Execute a read-only SQL query on invoice data",
     "parameters": {"sql": "string"}},
]
# LLM receives tools + user question → decides which to call
```

**Multi-hop example**:
1. User: "What did we buy from the vendor who issued INV-2025-0033?"
2. LLM calls `lookup_invoice("INV-2025-0033")` → gets vendor = "BuildMart Materials"
3. LLM calls `run_sql("SELECT * FROM invoice_chunks WHERE content_json->>'vendor' = 'BuildMart Materials'")` → gets all their invoices
4. LLM synthesizes the answer

**Risk**: Requires a capable LLM with function-calling support. The current Qwen3-VL-4B may struggle with complex tool chains. Test with simple 2-step chains first.

---

### Idea 8: Chunk-Per-Field Embedding (Granular Chunks)
**Effort**: ~2 hours | **Expected Impact**: Vector search improves for field-specific queries

Currently, each invoice is one big markdown chunk (~300 tokens). The embedding represents the average meaning of the entire document. When the user asks about a specific field, the embedding can't differentiate.

**Alternative**: Create multiple smaller chunks per invoice, one per logical field group:
```
Chunk 1: "Invoice INV-2025-0001 | Vendor: Summit Hardware | Date: 2026-03-21 | Buyer: Johnson LLC"
Chunk 2: "Invoice INV-2025-0001 | Line Items: Laptop x12 @ MYR 1267.55 = MYR 15210.60"
Chunk 3: "Invoice INV-2025-0001 | Subtotal: MYR 15210.60 | Tax: 6% (MYR 912.64) | Grand Total: MYR 16123.24"
```

**Why**: Each chunk's embedding is tighter and more specific. "What is the grand total?" now has higher cosine similarity to Chunk 3 specifically.

**Trade-off**: 200 invoices × 3 chunks = 600 database rows. More storage, more HNSW graph nodes, but still trivially small.

---

### Idea 9: Hybrid Architecture — SQL for Structure, RAG for Conversation
**Effort**: ~3 hours | **Expected Impact**: Best of both worlds

The most architecturally clean solution. Separate the system into two paths:

```
User Query
   │
   ├── Structured Path (SQL Engine)
   │   ├── Direct field lookups
   │   ├── Aggregations (SUM, COUNT, GROUP BY)
   │   ├── Date range filters
   │   └── Returns: precise values
   │
   └── Conversational Path (RAG Pipeline)
       ├── Fuzzy queries ("any large orders recently?")
       ├── Explanatory queries ("summarize vendor performance")
       └── Returns: generated text with context
```

**Implementation**: The query router (Idea 2) dispatches to either a SQL engine or the existing RAG pipeline. The LLM prompt is different for each path — one formats SQL results into natural language, the other synthesizes from retrieved text chunks.

---

## Quick-Win Experiment Plan (Recommended Order)

| Priority | Idea | Time | What You Learn |
|:---:|---|:---:|---|
| 1 | **Idea 4**: Weighted RRF | 15 min | Does keyword weighting alone fix MRR? |
| 2 | **Idea 6**: Fix FTS tokenization (`simple` dict) | 45 min | Does fixing tokenization break the 48% cap? |
| 3 | **Idea 1**: Direct JSONB ID lookup | 30 min | Does regex + SQL bypass solve ID queries? |
| 4 | **Idea 2**: Query intent router | 1 hr | Can rule-based routing combine all strategies? |
| 5 | **Idea 5**: Metadata columns + pre-filter | 1.5 hr | Does pre-filtering improve vector search? |
| 6 | **Idea 3**: Text-to-SQL generation | 2 hr | Can the LLM write correct SQL? |
| 7 | **Idea 8**: Chunk-per-field embedding | 2 hr | Do smaller chunks improve vector accuracy? |
| 8 | **Idea 7**: Agentic RAG (tool-calling) | 3 hr | Can the LLM orchestrate multi-step queries? |
| 9 | **Idea 9**: Full hybrid SQL + RAG architecture | 3 hr | End-state architecture validation |

---

## Recommendation

Start with **Ideas 1 + 2 + 4** together (~1.5 hours total). This gives you:
- A regex ID extractor that short-circuits to direct JSONB lookup (solves ~90% of current test queries)
- A simple router that falls back to weighted hybrid search for everything else
- No schema changes, no re-ingestion, no new models

This combination alone should push Hit Rate from 51% → 90%+ and MRR from 0.31 → 0.85+.

Then experiment with **Idea 6** (FTS tokenization fix) and **Idea 3** (Text-to-SQL) to handle aggregation and edge cases.
