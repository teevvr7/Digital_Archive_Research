# 2026-07-27 — Documentation pass: database schema doc + code-comment batch 1

**Branch:** `mvp3-prod`

---

## Context

User asked for two things: (1) add clear comments throughout the codebase explaining the usage
of each line/function, done batch by batch, then (2) update `read.md` with a "how to run the
system" section. Partway through starting batch 1, a mid-task request came in to also create a
standalone `database-scheme.md` documenting the database schema — addressed immediately since it
was well-scoped and I already had fresh schema context loaded from reading every model file for
the comment pass.

## Scoping the comment pass

Before touching code, sized the task and asked two calibration questions rather than guessing:
backend is ~90 source files (excl. tests/migrations) + 30 tests + 17 migrations; frontend is
~35 files. Most functions already carry solid docstrings (visible throughout the last two days'
work), so the register mattered — asked (1) how dense the comments should be, and (2) where to
start.

**Answers:** maximal density (docstring on every function *and* an inline comment on nearly every
line, even simple ones — heavier than the "audit + fill gaps" alternative I'd have defaulted to),
starting with `backend/app/core/` + `backend/app/models/` as batch 1 (the shared foundation every
other module depends on).

## `database-scheme.md` (new file)

A complete, standalone reference for all 18 tables — columns, types, nullability, defaults,
foreign-key behavior (CASCADE/SET NULL/RESTRICT explained per column), the document status state
machine, how relationships trace back to `tenants`, notable indexes, the RLS policy mechanism
explained in plain English (including *why* the fail-closed `NULLIF(..., '')` pattern exists),
and the full migration history through `0016`.

Cross-checked against the actual current model files rather than copied from `read.md`'s existing
(and already excellent) database section — that section was stale: it said "17 tables" and
"current head: 0014", missing both `document_type_fields` (migration `0015`) and the two
trash-retention columns on `tenants` (migration `0016`). `database-scheme.md` reflects the true
current schema; `read.md`'s equivalent section still needs the same refresh (see "Next" below).

## Code-comment batch 1 — `app/core/` + `app/models/`

31 files (12 in `core/`, 19 in `models/`, ~1,463 lines before commenting). Every function/class
got a docstring where one was missing; nearly every line of substantive code got an inline
comment — not just "what" (`is_default: bool = False  # auto-loads if true`) but the "why" where
it mattered (e.g. `uploaded_by` uses `RESTRICT` instead of `CASCADE`/`SET NULL` — commented with
the reason: a user with documents attached can't be deleted out from under them; the RLS
`NULLIF(current_setting(...), '')` pattern — commented with why an unset GUC must fail closed
rather than raise or default to "no filter").

No logic was changed anywhere — this was a pure documentation pass.

## Verification

- `python -c "import app.models; import app.core...."` — every touched module still imports
  cleanly (would have caught any accidental syntax error from the edits).
- Full `pytest`: **394 passed**, both before and after a subsequent `black` reformatting pass
  (some trailing inline comments pushed lines past the 100-char limit; `black` re-wrapped them
  without touching comment content or logic).
- `black --check` → `black` (no-op verification, then the actual fix) on every touched file.

## Next

- **Code-comment batches remaining**: the ~15 backend feature modules (auth, files, search, tags,
  correspondents, metadata, views, bulk, export, shares, idp, worker — the bulk of the ~90
  backend source files), then backend tests (~30 files) and migrations (~17 files), then the
  frontend (~35 files across app pages, components, lib). Suggested order: one backend module at
  a time, frontend last.
- **`read.md` update** (the original request's second half, not yet started): add a "How to Run
  the System" section (env setup, `alembic upgrade head`, `uvicorn`, `python -m app.worker`,
  `npm run dev`, `pytest`) and refresh the stale parts — table count (17 → 18), migration head
  (0014 → 0016), and mention of the security-hardening + trash-retention work done 07-22/23,
  none of which the file currently reflects.
- Standing items unchanged from the 07-23 log: 13 commits sitting locally on `mvp3-prod`, still
  unpushed; the detail-page race condition; a real worker-processing pass; the remaining security
  roadmap phases; 2 of 7 Level 5 SME features.
