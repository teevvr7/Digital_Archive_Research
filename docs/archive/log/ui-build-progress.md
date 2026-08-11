# UI Build Progress Log

**Project:** DataWiz Digital Archive — Frontend UI
**Date:** 2026-06-04
**Session:** Sprint 0 — UI Scaffolding

---

## Objective

Build a fully interactive multi-page frontend for the DataWiz Digital Archive system.
Goal: pages must replicate the look and feel of the finished production product.
No backend is connected yet — all data uses realistic Malaysian mock data.

---

## Tech Stack Chosen

| Layer | Technology |
|---|---|
| Framework | Next.js 16 (App Router) |
| Language | TypeScript |
| Styling | Tailwind CSS v4 |
| Components | shadcn/ui (base-nova style, neutral color) |
| Icons | lucide-react |
| Mock data | In-memory TypeScript, no API calls |

---

## Files Created

### Types & Data

| File | Purpose |
|---|---|
| `types/index.ts` | Shared TypeScript types: `Document`, `Tenant`, `User`, `ActivityEvent`, `ProcessingStatus`, `DocumentType` |
| `lib/mock-data.ts` | Realistic mock data — 4 users, 8 documents (across all pipeline states), activity feed, tenant |
| `lib/utils.ts` | shadcn `cn()` utility |

### Shared Components

| File | Purpose |
|---|---|
| `components/sidebar.tsx` | Dark sidebar with logo, nav links, storage meter, user row, tenant pill |
| `components/status-badge.tsx` | Coloured status pill for all 6 IDP pipeline states with animated dots |

### App Layout

| File | Purpose |
|---|---|
| `app/layout.tsx` | Root layout with Geist fonts |
| `app/page.tsx` | Root redirect → `/login` |
| `app/(app)/layout.tsx` | App shell wrapping sidebar + main content area |

### Pages Built

| Route | File | Description |
|---|---|---|
| `/login` | `app/login/page.tsx` | Split-pane login: left = branding/stats/testimonial, right = form with show/hide password, demo credentials hint, simulated 1.2s auth |
| `/dashboard` | `app/(app)/dashboard/page.tsx` | 4 stat cards, recent documents table, storage donut, live activity feed |
| `/documents` | `app/(app)/documents/page.tsx` | Full data table with search, status/type/sort filters, tag chips, action buttons |
| `/documents/[id]` | `app/(app)/documents/[id]/page.tsx` | Document viewer — PDF/image preview mockup, 3-tab right panel (Extracted Data, Metadata, Raw JSON with collapsible tree) |
| `/upload` | `app/(app)/upload/page.tsx` | Drag-and-drop upload zone, per-file document type selector, animated upload progress, IDP pipeline explanation |
| `/search` | `app/(app)/search/page.tsx` | Full-text search with keyword highlight, type/date filters, suggested queries, search capability explainer |
| `/settings` | `app/(app)/settings/page.tsx` | 5-tab settings: Organisation, Users & Access, API Keys, Security (toggles), Notifications |

---

## Mock Data Summary

**Tenant:** Syarikat Maju Sdn Bhd (Professional plan, 2.65 GB / 10 GB)

**Documents (8 total across all pipeline states):**
- `completed` — TNB Invoice, Vendor Contract, Parking Receipt
- `ai_extraction` — Q1 Financial Report (in flight)
- `ocr_processing` — Telekom Invoice (in flight)
- `extracting_text` — HRDF Levy Form (in flight)
- `queued` — Petronas Fuel Invoice
- `failed` — LHDN Tax Notice (encrypted PDF)

**Users:** Ahmad Razif (admin), Siti Nurhaliza, Lee Wei Ming, Raj Kumar

---

## IDP Pipeline Visual States

All 6 states are represented in the mock data and shown with coloured animated badges:

| State | Colour | Animation |
|---|---|---|
| `queued` | Grey | Static |
| `extracting_text` | Blue | Pulse dot |
| `ocr_processing` | Green | Pulse dot |
| `ai_extraction` | Violet | Pulse dot |
| `completed` | Green | Static |
| `failed` | Red | Static |

---

## Status: COMPLETE ✓

All pages built, dependencies installed, TypeScript clean (0 errors), dev server running at `http://localhost:3000`.

- [x] All packages installed: `lucide-react`, `clsx`, `tailwind-merge`, `class-variance-authority`, `recharts`, `date-fns`, `tw-animate-css`
- [x] Dev server running at `http://localhost:3000`
- [x] TypeScript: 0 errors (`npx tsc --noEmit`)
- [x] Login page verified — full HTML rendering confirmed
- [x] Dashboard page verified — sidebar, stat cards, activity feed rendering
- [x] Document viewer `/documents/doc_001` verified — sidebar, extracted data panel confirmed
- [x] Fixed React hooks-in-map bug in Settings (extracted `ToggleRow` and `NotifRow` components)

---

## Design Decisions

- **Dark sidebar / light content area** — standard SaaS layout, maximises screen real estate for documents
- **Malaysian context** — organisation name, currency (MYR), TNB/Telekom/LHDN/Petronas vendors, PDPA compliance note
- **No external search cluster** — search capability panel explains the PostgreSQL-native approach (tsvector + pg_trgm + GIN)
- **IDP pipeline transparency** — status badges and upload page explain the cost-cascade pipeline to the user
- **Processing pipeline visible** — documents in-flight show which stage they're at (extracting text, OCR, AI)

---

## Next Steps (Post-UI)

1. Wire up real FastAPI backend (Sprint 1)
2. Connect Supabase Auth to the login flow
3. Replace mock data with real API calls via `lib/api.ts`
4. Add PDF.js or iframe for real document preview
5. Implement real-time pipeline status updates (SSE or polling)
