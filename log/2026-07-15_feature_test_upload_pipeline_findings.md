# Feature Test Pass — Upload/IDP Pipeline Findings
**Date:** 2026-07-15
**Branch:** `mvp-lvl2`
**Context:** Ran backend/worker/frontend fresh, fixed a LAN-access login issue (see `2026-07-15_lan_login_cross_origin_fix.md`), then did a guided step-by-step walkthrough of the feature set, starting at Phase 2 (Upload & Ingestion). Testing surfaced three real findings — one pre-existing/known, two new. Nothing in this doc has been code-fixed yet except the one-time job-queue unstick; fixes are proposed, pending approval.

---

## Finding 1 — OCR jobs stuck in "Queued" (Windows RQ scheduler gap, known limitation)

**Symptom:** A phone-camera photo (`image.jpg`, 3.1 MB) sat in `Queued` status for 5+ minutes after upload.

**Root cause:** RapidOCR's ONNXRuntime inference failed (`bad allocation`), triggering RQ's `Retry(max=3)` backoff. The retry got scheduled into the `rq:scheduled:idp` sorted set — but `app/worker.py`'s Windows branch runs `SimpleWorker([queue], connection=conn).work()` **without `with_scheduler=True`**, so overdue scheduled jobs are never auto-promoted back into the live queue on Windows dev. This is the same limitation documented in `log/2026-06-30_worker_matching_fix.md` and `read.md:887` ("Linux/other: `rq.Worker(with_scheduler=True)`... Windows: `SimpleWorker`, no retry scheduling") — a known, previously-accepted dev-only gap, not a new regression. Production runs on Linux, where the scheduler works.

**Action taken:** Ran the same one-time manual-promotion script as the June 30 fix. Found **23 overdue scheduled jobs backlogged** (far more than just today's one test upload — this had been silently accumulating). Requeued all 23.

**Result of requeue:** 3 succeeded outright; 6 failed again with OCR memory errors (see Finding 2); none have permanently exhausted all retries yet, but several — including the original `image.jpg` — are down to their last attempt. They'll get stuck in the scheduled registry again once that attempt fires and fails, requiring another manual promotion (the underlying Windows scheduler gap is still unfixed).

**Not yet decided:** whether to enable `with_scheduler=True` on the Windows/`SimpleWorker` branch too. Confirmed via `rq/scheduler.py` that `ForkProcess` already falls back to plain `multiprocessing.Process` (spawn) when the `fork` context isn't available, so it's plausible this would just work on Windows — untested. Left alone for now since it touches the worker process model.

---

## Finding 2 — OCR failures are a real memory-capacity issue, not a code bug

**Symptom:** Multiple image-OCR retries failed with escalating specificity: first `ONNXRuntimeError: ... bad allocation`, then explicit `numpy._core._exceptions._ArrayMemoryError: Unable to allocate 34.7 MiB for an array with shape (3008, 4032, 3)`.

**Root cause, confirmed by checking system memory directly:** this machine has **9.9 GB total RAM with only 0.6 GB free** at time of testing. Top consumers: the RQ worker's own Python process (1.4 GB — RapidOCR's ONNX models loaded in memory), Windows Memory Compression (1.2 GB, itself a symptom of pressure), plus Edge, VS Code (×2), Docker Desktop + its WSL2 VM, and Claude Code all running concurrently. A 34.7 MiB allocation failing is not about image size — it's a machine with almost no free memory left. Every image-OCR job attempted during this window failed for this reason.

**Status:** No code changes made — this is an environment/capacity constraint, not a pipeline defect. Further image-upload testing on this machine should wait until memory pressure is reduced (e.g. closing Docker Desktop/WSL2 or other apps) or be deferred to a less memory-constrained environment.

---

## Finding 3 — Daily report mislabeled "Invoice" (upload-page default, not a classifier bug)

**Symptom:** `IT_Support_Intern_Daily_Report-14_7_2026.docx.pdf` — clearly not an invoice — showed up with `document_type: Invoice`, `status: Completed`.

**Investigation (initial theory, ruled out):** First suspected the keyword gate in `idp/extract.py::detect_candidate_type()`, which flags a document as an invoice on the bare substring `"invoice"` anywhere in the text — plausible if the report mentions "resolved a client invoice issue." Queried the DB directly to check.

**Actual root cause:** `documents.extracted_data` is genuinely `NULL` for this document, and there's no `extractions` audit row at all — meaning the deterministic extractor never even produced a candidate, and `jobs.py` only overwrites `doc.document_type` on a **gate pass** (`idp/jobs.py:231`). Since that never happened here, `document_type` was never touched by the pipeline — it's whatever was set **at upload time**.

Traced to `frontend/app/(app)/upload/page.tsx:98`:
```ts
const [defaultType, setDefaultType] = useState<DocumentType>("invoice");
```
The upload page's "Default document type" selector hardcodes to **"Invoice"** on every fresh session, applied to every file dropped unless the user manually clicks a different type button first. This silently mislabels any non-invoice upload (reports, contracts, letters) and conflicts with the product's own north star ("general-purpose archive for ALL kinds of files... a file is never blocked or mislabeled just because structured extraction doesn't apply").

**Proposed fix (not yet applied, pending approval):** change the default to `"other"` — matches the backend's own fallback (`document_type=type_hint or "other"` in `files/service.py:299`), so behavior is consistent whether or not a hint is sent, and documents only get typed "Invoice" when the pipeline actually confirms it or the user deliberately chooses it.

---

## Bonus discovery — pre-existing `needs_review` backlog

Found **20 documents** (`batch2-0225.jpg` through `batch2-0241.jpg`) sitting in `needs_review` status with `document_type: invoice` since **2026-07-09** — leftover from an earlier test session, unrelated to today's testing. Not actioned; flagged as good real test data for the exception-review/correction UI in a future test phase.

---

## Status / next steps
- No permanent code fixes shipped yet from this session — all three findings are diagnosed, one has a proposed one-line fix awaiting go-ahead (upload default type), one is an environment constraint (system memory), one is a known accepted dev-only limitation (Windows RQ scheduler).
- Testing paused before Phase 3 (search/filters, tags/correspondents, exception-review UI) to log these findings first.
