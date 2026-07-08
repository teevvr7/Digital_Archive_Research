# Bug Fix — Worker Not Processing Jobs (Phase 4 Auto-matching SQL Bug)
**Date:** 2026-06-30  
**Branch:** `mvp-lvl2`  
**Symptom:** After Phase 4 was deployed, uploaded documents stayed in `queued` status forever. Worker started and logged "Listening on idp..." but never picked up jobs.

---

## Root cause

`app/modules/tags/matching.py` line 93 used SQLAlchemy's generic `.prefix_with()` to attempt `ON CONFLICT DO NOTHING`:

```python
# WRONG — generates: INSERT ON CONFLICT (...) DO NOTHING INTO document_tags ...
from sqlalchemy import insert
db.execute(
    insert(DocumentTag)
    .values(...)
    .prefix_with("ON CONFLICT (document_id, tag_id) DO NOTHING")
)
```

`.prefix_with()` inserts text immediately after the `INSERT` keyword, producing invalid PostgreSQL syntax. This caused a `psycopg.errors.SyntaxError` which aborted the transaction. Because the exception was swallowed by the crash-isolation try/except in `jobs.py`, the job appeared to continue — but the aborted transaction then caused the final `db.commit()` to raise `InFailedSqlTransaction`, crashing the job outright.

Since `Retry(max=3)` was configured, each failed job cycled back into the `rq:scheduled:idp` sorted set. Combined with the fact that **RQ SimpleWorker on Windows does not auto-promote overdue scheduled jobs**, all jobs piled up invisibly in the scheduled registry and were never executed.

---

## Fix

**`app/modules/tags/matching.py`**  
Replace plain `sqlalchemy.insert` with the PostgreSQL dialect insert:

```python
# CORRECT
from sqlalchemy.dialects.postgresql import insert

db.execute(
    insert(DocumentTag)
    .values(...)
    .on_conflict_do_nothing(index_elements=["document_id", "tag_id"])
)
```

---

## Manual recovery (one-time)

After deploying the fix, 24 jobs were stuck in the scheduled registry. Promoted them manually:

```python
import redis, time
from rq import Queue
from rq.registry import ScheduledJobRegistry
r = redis.Redis()
q = Queue('idp', connection=r)
registry = ScheduledJobRegistry(queue=q, connection=r)
for jid in registry.get_jobs_to_schedule(timestamp=time.time()):
    registry.requeue(jid)
```

---

## Result
- `big-invoice.pdf` (today's upload): status=`completed`, confidence=0.91 ✅
- `100-charles.pdf`: status=`completed` ✅
- All Phase 4 smoke test steps verified ✅

## Lesson learned
Any `INSERT ... ON CONFLICT` on PostgreSQL must use `from sqlalchemy.dialects.postgresql import insert`, not `from sqlalchemy import insert`. The generic insert has no `.on_conflict_do_nothing()` method; `.prefix_with()` is NOT a substitute.
