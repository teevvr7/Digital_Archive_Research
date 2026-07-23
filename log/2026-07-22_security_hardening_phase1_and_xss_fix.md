# 2026-07-22 — Security hardening: Phase 1 baseline + stored-XSS fix in search

**Branch:** `mvp3-prod`

---

## Context

User asked for a proper, incremental security plan — start simple, escalate later. Audited the
current posture first (backend + frontend) before writing anything: the baseline was already
strong (RLS-enforced multi-tenancy, JWT verification with HS256/asymmetric support, RBAC,
targeted rate limiting, magic-byte upload validation + quota, signed URLs, token-gated shares,
audit trail). Planned a 5-phase roadmap; this pass covers **Phase 1** (baseline hardening) plus
one item pulled forward from Phase 2 after the audit surfaced a real, high-severity bug.

## Found during the audit: stored XSS in the search snippet (HIGH)

`search/query.py::snippet_expr` builds a Postgres `ts_headline(...)` snippet that
`search/page.tsx` renders straight into the DOM via `dangerouslySetInnerHTML`. The existing code
comment claimed `ts_headline` escapes the source text — **it does not**; it only inserts the
literal `StartSel`/`StopSel` strings around matched terms and leaves the surrounding document
text untouched. A document whose extracted text contained `<img src=x onerror=...>` (plausible
from any OCR/parsed upload with adversarial content) would execute in a victim's browser the
moment it showed up in their own search results — a path to stealing the Supabase access token
out of `localStorage` and taking over the account/tenant.

**Fix:** `_HEADLINE_OPTS` now wraps matches in sentinel control characters (`\x01`/`\x02`,
illegal in real text) instead of literal `<mark>` tags. A new `snippet_html_safe()` HTML-escapes
the *entire* raw string first, then swaps the escape-proof sentinels for real `<mark>`/`</mark>`
— so nothing from the source document can inject markup, but highlighting still works. Wired into
`search/service.py`. Corrected the now-false claims in `search/schemas.py`'s docstring and added
an explanatory comment at the frontend `dangerouslySetInnerHTML` call site so a future change
can't reintroduce this silently.

**Regression test:** `test_search_service.py::test_snippet_neutralizes_html_in_extracted_text` —
seeds a document whose `extracted_text` contains an `onerror` payload, searches for it, asserts
the returned snippet contains no raw `<img`/`<script` and that the payload survives only as
escaped entities alongside real `<mark>` tags. Full 386-test suite green afterward.

## Phase 1 — baseline hardening

- **Security headers on every API response** (`core/security_headers.py`, new): `nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy`, `Cross-Origin-Opener-Policy`, `Permissions-Policy`,
  and a locked-down `Content-Security-Policy: default-src 'none'` (the API only ever returns
  JSON). Docs routes (`/api/docs`, `/api/redoc`, `/api/openapi.json`) are exempted from the CSP
  so Swagger/ReDoc's CDN-hosted assets keep working in dev. `Strict-Transport-Security` only
  fires when `ENV=production`. Verified live against a real running dev server, not just
  TestClient — headers present on `/login` and `/documents`.
- **API docs gated off in production** — `docs_url`/`redoc_url`/`openapi_url` are `None` when
  `ENV=production`, so the full schema isn't publicly enumerable; unchanged in dev.
- **Production error hygiene** — a catch-all `Exception` handler is registered *only* when
  `ENV=production`, returning a generic JSON 500 and explicitly calling
  `sentry_sdk.capture_exception` so the real error is still tracked. Dev keeps FastAPI's default
  (verbose) behavior completely untouched — zero risk to local debugging.
- **Global rate-limit fallback ceiling** — `default_limits=["200/minute"]` added to the shared
  `Limiter`, keyed by IP, on top of the existing stricter per-endpoint limits (signup, upload,
  share-resolve). Caught during implementation: since `default_limits` applies to *every* route
  via `SlowAPIMiddleware` (unlike the old per-endpoint-only limits), this newly makes Redis
  availability load-bearing for routes that never needed it before (list/search/health). Added
  `swallow_errors=True` so a Redis outage fails open on this defense-in-depth ceiling (skip +
  log) instead of 500ing every request — matches the project's "degrade gracefully" rule.
- **Input validation tightening** — new `core/validation.py::EmailField` (a lightweight regex +
  length-cap validator, deliberately *not* pydantic's `EmailStr` since that needs the
  `email-validator` package — not worth a new dependency for a check this simple). Applied to
  signup, invite, and correspondent email fields. Added explicit `max_length` bounds to the
  actual free-text input fields (org name, tag/correspondent name + match pattern, custom-field
  name, document title) — **not** a blanket model-level cap, after checking that `DocumentOut`
  and other *Out* schemas legitimately carry long text (`extracted_text`) that a global cap would
  have broken. Custom-field *values* (`Any`-typed, so pydantic's normal str constraints don't
  apply) get their own explicit length-capping validator.
- **Frontend security headers** (`next.config.ts`) — `nosniff`, `X-Frame-Options`,
  `Referrer-Policy`, `Permissions-Policy` on every route. Confirmed the upload page's camera
  capture uses a plain `<input capture="environment">` file picker (not `getUserMedia()`), so
  locking down the `camera` permission doesn't break it. **Did not** add a full page CSP this
  pass — got the zero-risk headers in, but a Next.js CSP needs to account for dev-mode HMR
  (inline eval) and Supabase's own fetch calls without live-testing both dev and prod builds
  first; flagging as a follow-up rather than shipping something unverified that could blank-page
  the app.
- **Dependency vulnerability scan** — added `pip-audit` as a backend dev dependency, ran it
  against the actual project venv (not the global Python install, which the first attempt
  accidentally audited and returned dozens of irrelevant findings from unrelated tools like
  torch/streamlit). **Clean** — the only finding was `pip` itself being outdated, fixed by
  upgrading it. `npm audit` on the frontend flagged 3 vulnerabilities (1 moderate `postcss` XSS,
  2 high `sharp`/libvips CVEs) — both are optional dependencies **bundled inside `next` itself**
  for its image-optimization pipeline; confirmed the app never imports `next/image` anywhere, so
  that code path is dead and real exposure is effectively nil. Bumped `next`
  16.2.7 → 16.2.11 (same major, patch-level, `eslint-config-next` matched) hoping for an upstream
  fix — the vulnerable bundled versions are unchanged even in the latest release, so this is
  upstream-blocked, not something fixable from our side; documented to revisit when Next.js ships
  updated bundled deps.

## Verification

- `pytest`: **386 passed** (full suite, including the two new test files/additions).
- `ruff` + `black`: clean on every touched file (fixed the handful of new-code violations —
  line length, import order — introduced by this pass; confirmed via careful line-by-line review
  that the small number of remaining findings in `auth/router.py` and `search/query.py` predate
  this change and sit outside every line touched here).
- `tsc --noEmit` + `eslint`: same pre-existing 26-problem baseline (2 `search/page.tsx` type
  errors, unrelated) — zero new issues from either the header config or the XSS-fix comment.
- Live-server check: started the real Next.js dev server (not just TestClient) and curled
  `/login` and `/documents` directly to confirm headers are actually present on real HTTP
  responses, not just asserted in tests.

## Not done this pass (Phases 2–5, per the approved roadmap)

- Frontend CSP (flagged above — needs live dev+prod testing before shipping).
- Safe inline-download `Content-Disposition` hardening for browser-renderable-but-risky types
  (SVG/HTML) — Phase 2 remainder.
- Account/session security (Supabase dashboard password policy, leaked-password protection,
  email verification gating, MFA) — Phase 3, needs manual dashboard steps handed to the user.
- Extended audit-trail coverage + automated security regression tests (headers/tenant-isolation/
  auth-required-everywhere) — Phase 4.
- Cookie-based auth, PDPA retention tooling, WAF/pen-test — Phase 5, only if/when needed.

## Next

9 commits from 07-20/07-21 plus today's security work now sit locally on `mvp3-prod`, still not
pushed to `origin`. The detail-page race condition and a real worker-processing pass (both
flagged 07-21) are still outstanding. Recommend deciding on push timing and picking the next
target (more security phases vs. the outstanding UX items) explicitly rather than defaulting.
