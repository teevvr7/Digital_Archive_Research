I've tagged each idea (S) small / (M) medium effort, and cut anything that would inflate complexity.

1. Automating tags, correspondents, and document type

First, an honest observation: you already have more automation built than you're using. Phase 4 shipped a rule-based match engine (modules/tags/matching.py — literal/any/all/regex algorithms) that auto-assigns tags and correspondents when a document finishes processing. The real gaps are UX and coverage, not missing machinery. So the simple ladder is:

- (S) "Create rule from this document" — when you manually tag a doc or set its correspondent, offer a one-click "always do this for documents like this" that pre-fills a match rule from the document's content. Today rules are created blind on the Tags/Correspondents pages; this flips it to learn-by-example.
- (S) Retroactive rule application — rules currently only run on new documents at pipeline completion. Add an "apply rules to existing documents" button (per tag/correspondent, or global). Paperless-ngx he backfill job through the existing engine.
- (S) Email sender → correspondent — for .eml files you already parse headers; auto-create/link the correspondent from the From: address. Nearlfree, very high hit rate.
- (S) Document-type keywords in the DB — document_types is already dynamic DB data. Add a keywords column per type and run it through the same matching engine at ingest. Zero ML, per-tenant customizablsetting.
- (M) "Auto" classifier, paperless-style — once tenants accumulate confirmed examples: per-tenant TF-IDF + linear classifier (scikit-learn,
CPU-only, pip-only) over extracted_text, retrained nightlygs/type/correspondent. Suggest below a confidence threshold, auto-apply above it, and show why ("matched rule X" / "87% similar to your other Maybank invoices"). Every accept/reject feeds the next retrain —
this is exactly the self-learning loop your CLAUDE.md alreoven design paperless uses; it's the right ceiling for now.

Do them in that order — the four (S) items alone will killre you touch ML.

2. Getting value from the extraction JSON (beyond RAG)

The JSON's best uses are boring, deterministic, and direct

- (S) Auto-title — set title to {vendor} — {invoice_no} — ename. Title search now works, so this directly improves the headline feature.
- (S) Typed filters on extracted fields — amount-range film the JSON (this was in the original plan's search spec).Consider promoting total_amount/currency to real indexed columns — cheap migration, makes everything below fast.
- (S) CSV/XLSX export — select docs (or a saved view) → exreadsheet. Accountants live in Excel; this is the singlehighest-leverage JSON feature and it's a bulk-op away.
- (S) Duplicate-invoice detection — same vendor + invoice_hived → flag on upload. "We caught a duplicate payment" is a story that sells the product by itself. Pure SQL.
- (M) Due-date reminders — a scheduled job that surfaces "a dashboard widget or email digest, driven by the extracteddue_date.
- (M) Small spend widgets — monthly total by correspondentQL aggregates on the existing dashboard — not a BI module.(Note: "analytics dashboards" is on your do-not-build list, so this needs your explicit scope approval; I'd keep it to 2–3 widgets max.)
- (M, later) Webhook on completion — POST the JSON to a teoint, gives you "integrates with anything" without buildingintegrations.

3. SME-attracting features

SMEs buy zero-setup and immediate value, not feature lists:

- (M) Email-in ingestion — each tenant gets a forwarding address; forward a supplier invoice → archived + extracted automatically. Your .eml parser
already exists; the new part is inbound mail (Cloudflare EMAP-poll RQ job). This is the SME feature — it removes theupload step entirely.
- (S) Phone camera capture — PWA manifest + <input capture page. Snap a receipt, it uploads. Very cheap since OCRalready handles photos.
- (S) Onboarding starter kits — seed tags/types/corresponds profile (trading, F&B, services) at signup. Cutstime-to-value from an hour to zero.
- (S) Zip/bulk import — onboarding years of back-history i
- (M) Full-tenant export — zip of originals + metadata CSV/JSON. "No lock-in" builds SME trust and doubles as PDPA data-portability compliance.
- (M, timely for Malaysia) MyInvois e-invoice ingestion — tory for most SMEs. The practical first step is not APIintegration: just add the UBL XML/JSON e-invoice format to your parser registry. These files are already structured — no OCR, no VLM, 100%
deterministic extraction. A Malaysian archive that nativel real differentiator, and this first slice is genuinelysmall.

4. My add-ons: production hardening (known gaps, all practical)

- (S) Wire Sentry — the one unfinished Phase 0 item; needs only your DSN.
- (S) Rate limiting + upload batch-count cap — both flagge
- (M) Expand eval corpus to 30–50 real docs — you can't tune extraction or the future classifier without measurement; this blocks on you providing docs.
- (M) Replace the VLM placeholder's endpoint — it's unreachable half the time. Pointing the existing gate-fail seam at a cheap hosted vision API (e.g., Gemini Flash free tier, already contemplated in youexisting budget gate buys reliability with no architecturechange.
- (S) FTS language config — search is hardcoded to 'englis the simple config will recall better. One migration +reindex — worth it given the Malaysia target.                                                                                                   - (S) Auto-empty trash after N days + verify Supabase backne and data safety.
- (S) Deploy workers on Linux — the RQ SimpleWorker Windows quirks (scheduled-retry stalls, finding #8) disappear with the standard worker in a Linux container.
                                                                                                                                              Deliberately excluded (impractical right now)
                                                                                                                                              WhatsApp ingestion (API cost/approval overhead), accountint with CSV export), full MyInvois submission API (start with format ingestion), semantic/vector search and rerankers (already out of scope), native mobile app, per-tenant fine-tuned models.              
Suggested sequence                                                                                                                            
1. Quick-wins bundle (all S): rule-from-document + retroactive rules + email-sender correspondent + type keywords + auto-title + CSV export + duplicate-invoice flag.
2. Production bundle (S/M): Sentry, rate limits, FTS language, trash retention, eval corpus.
3. SME pack (M): email-in ingestion, camera capture, start
4. Auto-classifier (M): the paperless-style suggest/confirm ML layer, once bundle 1 has generated training data.
5. Differentiators (M): MyInvois ingestion, tenant export,