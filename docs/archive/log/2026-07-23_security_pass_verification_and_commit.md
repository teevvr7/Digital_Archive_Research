# 2026-07-23 — Security pass: formatting cleanup, live verification, commits

**Branch:** `mvp3-prod`
**Commits:** `4f7af42` (Phase 1 baseline), `edb5633` (search-XSS fix + log)

---

## Context

Tail end of the security-hardening pass started 2026-07-22 (see that log entry for the audit,
the stored-XSS finding, and the Phase 1 baseline design decisions). Everything built the day
before was already passing tests and lint; today finished formatting cleanup, re-verified after
that cleanup, proved the headers work against a real running server (not just `TestClient`), and
committed the work.

## Formatting cleanup

`black --check` flagged 4 files as unformatted (`main.py`, `search/query.py`, `auth/router.py`,
`test_search_service.py`) — ran `black` to reformat them, then re-ran `ruff check` to confirm
clean on every file this pass touched (excluding the small set of pre-existing findings in
`auth/router.py`/`search/query.py` identified and ruled out-of-scope the day before).

## Re-verification after formatting

- Full backend suite re-run post-formatting: **386 passed**, confirming `black`'s reformatting
  didn't silently change behavior.
- Live-server check: started the real Next.js dev server (not `TestClient`), polled until it
  was up, then `curl -I` against `/login` and `/documents` directly — confirmed
  `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, and `Permissions-Policy` are
  actually present on real HTTP responses, not just asserted by tests. Stopped the dev server
  afterward (found its PID via `Get-NetTCPConnection`, since Windows has no simple `fuser`
  equivalent).

## Committed

Split into the two commits the approved plan specified:

- **`4f7af42`** — Phase 1 baseline: security-headers middleware, docs gated off in production,
  production error handler, rate-limit fallback ceiling (with `swallow_errors=True`), input
  validation tightening, frontend headers, `pip-audit`/`npm audit` triage + the `next` patch bump.
- **`edb5633`** — the search-snippet stored-XSS fix, its regression test, and the 07-22 log entry.

Working tree left clean (only the pre-existing untracked `invoice2data-master/`/`paperless/`
reference dirs remain, as before).

## Next

11 commits now sit locally on `mvp3-prod` since the last push (the 9 from 07-20/07-21 plus these
2). Still not pushed to `origin` — no push has been authorized yet. Outstanding from prior days:
the detail-page race condition (same pattern already fixed on the documents list page) and a
real worker-processing pass. Outstanding from today: Phases 2 (remainder)–5 of the security
roadmap, and the deferred frontend CSP (needs live dev+prod testing before it can ship safely).
