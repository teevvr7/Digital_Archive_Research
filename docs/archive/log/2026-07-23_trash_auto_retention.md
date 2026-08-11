# 2026-07-23 — Trash auto-retention (Level 5)

**Branch:** `mvp3-prod`

---

## Context

One of the three remaining Level 5 (SME growth & differentiators) features. Trashed documents
previously sat forever until a user manually clicked "Empty Trash" — unbounded storage cost (the
project's #1 priority) and no PDPA-aware retention story. Added admin-configurable, per-tenant
auto-purge, mirroring how every comparable product (paperless-ngx, Gmail, Drive) handles trash.

## Mid-implementation architecture pivot

The original plan called for a background RQ job that periodically enumerated every tenant and
swept each one's expired trash. Partway through, hit a real blocker: **the `tenants` table itself
has RLS** (`id = current GUC`), so there is no way to run "list every tenant" through the normal
SQLAlchemy session — with no GUC set it returns zero rows, by design (fail-closed). Making that
work would have meant either bypassing RLS at the Postgres role level (a hard CLAUDE.md rule:
"Never connect as a role that bypasses RLS") or adding a new elevated-access channel.

Flagged this to the user before writing more code. Redesigned to **opportunistic, per-tenant
triggering** instead of a global sweep: `files/retention.py::maybe_purge_expired_trash(db,
tenant_id)` is called from two places that already run inside a given tenant's own RLS-scoped
session — viewing that tenant's Trash view, and finishing that tenant's own document-processing
job in the worker — so it never needs a session or tenant context beyond what's already open.
Rate-limited via a new `Tenant.trash_last_purged_at` timestamp (~once/24h), so it's a cheap no-op
on almost every call. Coverage is effectively complete for the actual goal: a tenant that isn't
uploading or visiting their trash isn't generating new storage cost either.

## What was built

- **Migration `0016`**: `tenants.trash_retention_days` (nullable override, NULL = global default
  — mirrors the existing `llm_monthly_token_cap` pattern exactly) + `tenants.trash_last_purged_at`
  (rate-limit timestamp).
- **`settings.trash_retention_days_default = 30`** (env `TRASH_RETENTION_DAYS_DEFAULT`).
- **`files/retention.py`** (new): `effective_retention_days(tenant)` (override-or-default) and
  `maybe_purge_expired_trash(db, tenant_id)` — the core purge logic, mirroring
  `files/service.py::empty_trash`'s swallow-storage-errors + `storage_used_bytes` accounting, but
  scoped to `deleted_at < cutoff` and recording one summary `ActivityEvent`
  (`user_name="system"`) per purge — unlike a user-clicked "Empty Trash," this happens with
  nobody watching, so it gets an audit-trail entry.
- **Two trigger points**: `files/service.py::list_documents` (when `trashed=True` — viewing the
  Trash view) and `idp/jobs.py::process_document` (after every document a tenant processes).
- **Admin settings**: extended `PATCH /auth/tenant` (`TenantPatchIn`/`TenantOut` +
  `update_tenant_settings`, renamed from `update_tenant_name` since it now does more) with
  `trashRetentionDays` (raw override) and a computed `effectiveTrashRetentionDays` (resolved
  value, so the frontend never duplicates the NULL-fallback logic). New input added to the
  existing Organisation Details card in Settings.
- **Trash-view countdown**: "Purges in N days" badge per row (table view), computed client-side
  from `deletedAt` + `tenant.effectiveTrashRetentionDays` via a new `lib/format.ts::
  daysUntilTrashPurge` helper — no new API call needed.

## Verification

- New `test_trash_retention.py` (DB-gated, real Postgres, RLS enforced) — 6 tests: expired vs.
  recent trash purged correctly, `storage_used_bytes` decremented, exactly one summary
  `ActivityEvent` recorded, the ~24h rate-limit actually no-ops a second call, override vs.
  default resolution, and a **dedicated cross-tenant isolation test** proving one tenant's sweep
  never touches another's documents. That last one needed its own committed (not rolled-back)
  seed data — rollback-based checks can't distinguish "no bug" from "bug happened, rollback
  erased the evidence," and RLS means one tenant's session can't even see another's rows to check
  them directly — verification goes through a superuser bypass connection instead, the same
  technique the other isolation-test fixtures already use for setup/teardown.
- Extended `test_settings_and_activity.py`'s tenant-update tests for the renamed function +
  new field (2 new tests: sets override, `None` clears it).
- Full `pytest`: **394 passed** (was 386; +8 from this feature).
- `alembic upgrade head`: applied cleanly.
- `ruff` + `black`: clean on every file this pass touched (reviewed each remaining ruff finding
  individually — all pre-existing debt on lines untouched by this change, or a codebase-wide
  accepted pattern like the migration boilerplate's `Union`/`Sequence` style and the pervasive
  `datetime.timezone.utc` usage — left alone rather than "fixed" in isolation, which would have
  made this change inconsistent with everything around it).
- `tsc --noEmit` + `eslint`: same pre-existing 26-problem baseline, zero new issues.

## Known limitations (not addressed this pass)

- The trash-view countdown only shows in table view — the grid view uses a separate `DocCard`
  component that wasn't touched; a fast-follow if it matters.
- No live browser click-through this pass — this is a backend-heavy feature (migration, worker
  job, RLS-sensitive logic) and no backend/worker/real-Supabase session was running; verification
  leaned on the DB-gated pytest suite (including the real-Postgres isolation test) plus static
  `tsc`/`eslint`. Worth a manual pass before relying on this in front of a real user: set a short
  retention on a test tenant, trash a doc, backdate `deleted_at`, confirm the Settings input and
  Trash countdown reflect reality end-to-end.
- Per-document-type or per-plan-tier retention rules, and a pre-purge warning email/notification,
  are explicitly out of scope for this pass (per the approved plan).

## Next

13 commits from 07-20 through this feature now sit locally on `mvp3-prod` (`1e2ec7f`), still not
pushed to `origin`. Remaining work, by thread:

- **Security roadmap** (Phase 1 + the search-XSS fix done 07-22/07-23): Phase 2 remainder (safe
  inline-download `Content-Disposition` for SVG/HTML), the deferred frontend CSP, Phase 3
  (Supabase dashboard password/MFA settings), Phase 4 (audit-trail + regression tests,
  `SECURITY.md`), Phase 5 (cookie-based auth, PDPA tooling — only if/when needed).
- **Carried over from the UX pass (07-20/21)**: the detail-page race condition on
  `documents/[id]/page.tsx` (same pattern already fixed on the list page, not yet fixed here); a
  real worker-processing pass (the IDP worker hasn't run this session); test-coverage gaps
  (`/search`, Dashboard, Saved Views, Correspondents, Settings' stub tabs, detail-page tabs,
  team-invite email flow, MyInvois ingestion — only 4 E2E specs exist).
- **Trash auto-retention follow-ups** (this feature): no live browser click-through was done yet
  — worth a manual end-to-end pass before relying on it in front of a real user; the grid view's
  `DocCard` doesn't show the retention countdown (table view only).
- **Level 5**: 2 of 7 SME features remain unstarted — email-in ingestion, Malay FTS config.
- **Level 2** (paddle_qwen IDP port): still blocked on the user's Lightning AI endpoint + license
  check.
