## Critical Review of `feature_planning.md`

### A. RAG Chatbot — Critical Flaws

**1. Qwen-VL is the wrong model for text generation.**
Qwen-VL is a **vision-language** model. It is architected to process images + text prompts for structured extraction tasks. Using it as a general-purpose conversational LLM (receiving pure-text RAG context and generating free-form answers) is a misuse. It will produce mediocre, stilted responses compared to a proper text-only LLM. You need a separate text generation endpoint — either a small local model (e.g., Qwen2.5-7B-Instruct, Phi-3-mini) or an API call to Gemini/GPT. The "zero additional cost" claim collapses here.

**2. SentenceTransformer loaded on every request is a latency killer.**
The retrieval code (`retrieve_relevant_contexts`) instantiates `SentenceTransformer("all-MiniLM-L6-v2")` on every single chat query. Model loading takes 2-5 seconds. This must be a singleton loaded once at process startup (same pattern you already fixed for PaddleOCR). The ingestion job has the same issue.

**3. Chunking strategy is naive and will produce garbage retrieval for invoices.**
500-char sliding window with 100 overlap is designed for long-form prose documents (legal contracts, reports). Your actual documents are invoices, receipts, and forms — these are **tabular and sparse**. A 500-char window will mash together unrelated line items, vendor headers, and footer totals into a single chunk, destroying retrieval precision. You need:
- **Structured chunk awareness**: Chunk by extracted JSON fields, not raw text blocks.
- **Hybrid retrieval**: Search over `extracted_data` JSON fields (keyword match) alongside vector similarity on `extracted_text`.

**4. No conversation memory or session management.**
The plan describes a stateless single-turn Q&A endpoint. Real chatbot UX requires multi-turn context (user asks follow-up questions). There is no `chat_sessions` table, no message history passed to the LLM, no session TTL management.

**5. pgvector HNSW index will not scale without tuning.**
The plan creates an HNSW index with default parameters. For production with tens of thousands of chunks, you need to specify `m` and `ef_construction` values. Default HNSW on Supabase free tier may also hit memory limits. This needs to be called out.

---

### B. SMB Value Loops — Critical Flaws

**6. The CSV export engine has a fundamental field-mapping fragility.**
The code hardcodes `data.get("vendor_name") or data.get("vendor", "")`. Your extraction output field names are **entirely dependent on the VLM prompt and JSON schema** — they are not standardised. Different templates, different document types, and different VLM runs can produce `"vendor"`, `"vendor_name"`, `"supplier"`, `"company_name"`, etc. This mapper will silently produce empty columns on most documents. You need a **canonical field normalisation layer** between extraction output and export, or let users define column mappings per document type.

**7. Math auditor assumes a single formula pattern.**
The `verifyInvoiceMath` function hardcodes `subtotal + tax + fees = grand_total`. Real-world invoices have discounts, multiple tax rates (GST + service tax), deposit deductions, line-item-level taxes, and rounding adjustments. A single formula will produce false-positive warnings constantly, training users to ignore the badge. Better approach: make verification rules configurable per document type template.

**8. Spend analytics on JSONB is a performance trap.**
Running SQL aggregations directly on `extracted_data` (a JSONB column) without materialised/computed columns or a proper data warehouse extraction means every analytics query does full-table JSONB parsing. This is fine for 50 documents, but will crawl at 5,000+. You need either:
- Materialised columns for common numeric fields (total, date, vendor), or
- A lightweight ETL into a flat analytics table on extraction completion.

**9. Webhooks section is a stub with no error handling design.**
Real webhook implementations need: retry queues with exponential backoff, delivery status tracking, HMAC signature verification, configurable event filters, and a delivery log UI. Simply "posting JSON on STATUS_COMPLETED" will result in silent data loss when the target endpoint is down.

---

### C. What is Missing Entirely

**10. No prioritisation or phasing.**
Everything is presented at equal weight. The plan needs a clear answer to: *"What do we ship in week 1 vs. month 2?"* CSV export is a weekend feature. RAG is a multi-week effort. They should not be in the same phase.

**11. No cost analysis.**
- How much additional storage does pgvector consume per document?
- What is the Supabase plan row/storage limit and will chunks blow past it?
- Does the rq worker have enough RAM to load SentenceTransformer alongside PaddleOCR?

**12. No user persona definition.**
"SMB" is vague. A 3-person accounting firm and a 50-person manufacturing company have completely different needs. The plan should define 2-3 concrete personas with specific workflows.

**13. No mention of document-level chat vs. archive-level chat.**
These are fundamentally different UX and retrieval scopes. "Ask about this invoice" (single-doc context) vs. "Show me all overdue invoices from vendor X" (cross-archive query on structured data). The second one doesn't need RAG at all — it needs a structured query interface or natural-language-to-SQL.

**14. No auth/permission model for chat.**
Can a user in tenant A see chunks from tenant B? The RLS policy for `document_chunks` is mentioned but not defined. Chat history itself also needs tenant isolation.

---

### D. Ideas Worth Pursuing Instead / In Addition

1. **Natural-language-to-SQL over extracted_data** — more useful for SMBs than RAG. "How much did we spend on vendor X last quarter?" translates to a SQL query on materialised fields, not a vector search over raw text. Faster, cheaper, more accurate.

2. **Template auto-learning from corrections** — when users correct VLM output, feed the correction pairs back as few-shot examples for future extractions of the same document type. This is a higher-value differentiator than a chatbot.

3. **Duplicate invoice detection** — SMBs overpay duplicate invoices constantly. Compare `(vendor_name, invoice_no, grand_total)` tuples across documents and flag matches. Trivial to implement, massive business value.

4. **Approval workflows** — extracted invoices need sign-off before payment. A simple status machine (extracted → reviewed → approved → exported) with user assignments would make this tool actually deployable in a team setting.

5. **Mobile-friendly document capture** — SMB owners photograph receipts on phones. A simple camera-upload flow with automatic orientation correction would dramatically increase ingestion volume.

---

### Summary Verdict

The plan demonstrates good instinct on resource reuse and cost consciousness. However, it conflates two very different products (semantic chat vs. operational tooling) without prioritising, and the RAG implementation has fundamental model-choice and chunking errors that would produce a poor user experience. The SMB features are closer to shippable but need a field normalisation layer to work across diverse extraction outputs.

**Recommended immediate action**: Ship CSV export + math audit + duplicate detection first. Defer RAG until you have a proper text-generation model endpoint and structured-aware retrieval.