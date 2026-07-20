# 2026-07-20 — Production-Feel UX Pass, Part A (toast/confirm/modal/skeleton/empty-state)

**Branch:** `mvp3-prod`
**Commits:** `db95633` (LAN dev-access fix, carried over from 07-15), `4d71a35` (predefined custom fields + type-gated filter, carried over from 07-16), `fed2f62` (this session's UX pass)

---

## Context

Picked up the session by first committing and pushing four days of uncommitted work from 07-15/07-16 (LAN dev-access fix + predefined-custom-fields feature, previously verified but left uncommitted pending manual testing — see `2026-07-16_predefined_custom_fields_and_filtering.md`). Split into two commits by theme and pushed to `origin/mvp3-prod`.

User then asked for a forward-looking plan: enhancements for better UX, plus what needs testing. Surveyed the frontend directly (not via subagent) before proposing anything: `frontend/components/ui/` was completely empty — every UI pattern (modals, feedback) was copy-pasted inline per page — and grepping surfaced **25 `alert()` + 9 `confirm()` calls across 8 pages** plus **5 hand-rolled `fixed inset-0` modals**, no loading skeletons (one bare spinner), undifferentiated empty states, and **zero automated frontend tests** (no Playwright/Vitest/Jest at all, versus 28 backend pytest files). Presented both findings via `AskUserQuestion`; user chose the most ambitious option on both: a full production-feel UX primitives pass (not just the feedback system — also skeletons, empty states, and the modal refactor), and Playwright E2E smoke tests (not just component tests).

Wrote and got approval for a two-part plan (`~/.claude/plans/compiled-moseying-tulip.md`): **Part A** — shared UI primitives + app-wide adoption (this entry). **Part B** — Playwright harness + golden-path specs (next).

---

## Part A — what shipped

**New primitives, `frontend/components/ui/`:**
- `toast.tsx` — `ToastProvider`/`useToast()`, portal-rendered, auto-dismissing (4s), `aria-live="polite"`, three variants (success/error/info).
- `confirm-dialog.tsx` — `ConfirmProvider`/`useConfirm()`, an async `confirm({title, body, confirmLabel, danger})` replacing `window.confirm`; `danger: true` styles the confirm button red for destructive actions. Built on `Modal`.
- `modal.tsx` — shared `Modal` shell: `createPortal`, backdrop-click + `Escape` to close, body scroll-lock, focus trap + initial focus, consistent `max-w-md` card styling matching what every hand-rolled modal already used.
- `skeleton.tsx` — base `Skeleton` shimmer + `TableRowsSkeleton`/`CardGridSkeleton` (mirroring the Documents page's real table/grid shapes) + `DetailSkeleton`.
- `empty-state.tsx` — `EmptyState(icon, title, description, action?)`.

Both providers mount once via a new `frontend/components/providers.tsx` client wrapper in the root `app/layout.tsx`, so toast/confirm work on every route including login/signup, not just the authenticated app shell.

**Adoption, all 8 flagged pages plus the upload popup:**
- `documents/page.tsx` (the bulk of it — 16 alert/3 confirm): every bulk action (trash, tag, set type, download, export) and single-doc action (retry, trash, restore, permanent delete, empty trash) now uses `toast`/`confirm`. Several previously-silent successes (bulk tag, save view) now confirm via `toast.success`. Loading spinner → `TableRowsSkeleton`/`CardGridSkeleton` matching the active view mode. Empty state is now context-aware: active filters → "No documents match these filters" + Clear filters CTA; no filters, not trashed → "No documents yet" + Upload CTA; trash view, empty → "Trash is empty", no CTA. Added `data-testid` hooks (`type-filter`, `custom-field-picker`, `bulk-tag-button`, `bulk-set-type-button`, `bulk-download-button`, `bulk-trash-button`) for Part B's specs to target.
- `tags/page.tsx`, `correspondents/page.tsx`, `settings/page.tsx` (invite modal), `documents/[id]/page.tsx` (share modal) — hand-rolled modals migrated onto `<Modal>`; alert/confirm replaced.
- `documents/[id]/page.tsx` — the page's top-level `if (!doc) return <Loader2 spinner>` loading state replaced with `DetailSkeleton`.
- `search/page.tsx`, `custom-fields/page.tsx`, `views/page.tsx` — single alert/confirm call sites replaced (no modal in these files).
- `upload/page.tsx` — the `FieldsModal` popup (predefined fields / create new / attach existing) migrated onto `<Modal>`; no alert/confirm was present here.

## Verification

- **tsc --noEmit**: clean — same 2 pre-existing, unrelated `search/page.tsx` errors as every prior session.
- **eslint**: ran `npx eslint .` on the full Part-A diff — 26 problems (20 errors, 6 warnings), all in files with `git diff --stat` showing zero changes (`login/page.tsx`, `signup/page.tsx`, `test_upload.mjs`) or in pre-existing `useEffect` bodies I didn't touch. To be certain, `git stash push -u -- frontend` then re-ran eslint against the exact pre-Part-A baseline: **identical 26 problems, same line numbers, same files** — confirmed zero new lint issues before popping the stash back. (The `react-hooks/set-state-in-effect` rule fires as `error`, not `warning`, in this eslint-config-next version — a baseline fact, not something this session changed.)
- **pytest**: not re-run — `git diff --stat -- backend` is empty; Part A touched zero backend files.
- **Live smoke check**: started both dev servers (backend via `PowerShell Start-Process`, discovered a healthy backend was already running on port 8000 from an earlier session — reused it rather than fighting a bind conflict; frontend via `npm run dev`, clean Turbopack startup, no compile errors). Fetched `/documents`, `/tags`, `/settings`, `/upload` — all 200, no server-side crash from the new components.
- **Not done**: no browser-automation tool is available in this session, so the actual visual/interaction pass (does a toast really appear and auto-dismiss, does Escape really close the confirm dialog, do the skeletons actually animate, do both empty-state variants render correctly) has **not** been eyeballed by me — only inferred from clean compiles/lints and correct code review. Left both dev servers running for the user to click through directly.

## Next

**Part B (not started this entry):** Playwright harness (`@playwright/test` dev dependency, `playwright.config.ts`, `e2e/global.setup.ts` logging in once via a dedicated test account) + 4 golden-path specs (auth, upload, the type-gated custom-field filter, bulk ops). Blocked on the user providing a throwaway `E2E_EMAIL`/`E2E_PASSWORD` test account on the live Supabase project — cannot proceed past scaffolding without it.
