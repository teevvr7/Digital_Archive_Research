# Bug Fix — Login Fails Silently When Accessed via LAN IP (Phone/Other PC)
**Date:** 2026-07-15
**Branch:** `mvp-lvl2`
**Symptom:** Backend, worker, and frontend all started cleanly (`curl /api/health` OK, worker listening on `idp`, frontend serving `/login` with 200). Accessing the app from `localhost:3000` on the dev machine worked fine. But opening `http://192.168.0.56:3000` (the LAN IP) from a phone — or from a completely different PC on the same network — showed the login page fully styled, yet submitting the form produced **no error message at all**; the page just visibly reloaded back to an empty login form.

---

## Investigation

Two distinct issues were found and fixed in sequence before the real root cause surfaced.

### 1. `NEXT_PUBLIC_API_BASE_URL` hardcoded to `localhost`
`frontend/.env.local` had:
```
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api
```
On a phone, `localhost` resolves to the phone itself, not the dev machine — so any call to the backend would fail. Changed to the LAN IP:
```
NEXT_PUBLIC_API_BASE_URL=http://192.168.0.56:8000/api
```

### 2. Backend CORS didn't allow the LAN origin
`backend/.env`:
```
CORS_ALLOW_ORIGINS=http://localhost:3000,http://localhost:3001
```
Even with #1 fixed, the browser would block the request as a CORS violation since `http://192.168.0.56:3000` wasn't an allowed origin. Added it:
```
CORS_ALLOW_ORIGINS=http://localhost:3000,http://localhost:3001,http://192.168.0.56:3000
```

Both of these were real, necessary fixes — but after restarting with both applied, the symptom persisted **identically**, including on a second desktop PC (not just the phone). That ruled out anything mobile-specific (Safari quirks, in-app browser storage restrictions, private-mode `localStorage` blocks) and pointed at something tied purely to the *origin* used to reach the Next.js dev server itself.

### 3. Real root cause: Next.js 16 dev-server cross-origin protection
`frontend/frontend_err.log` had the answer the whole time:
```
⚠ Blocked cross-origin request to Next.js dev resource /_next/webpack-hmr from "192.168.0.56".
Cross-origin access to Next.js dev resources is blocked by default for safety.
To allow this host in development, add it to "allowedDevOrigins" in next.config.js and restart the dev server:
  allowedDevOrigins: ['192.168.0.56'],
```
Next.js 16's dev server blocks cross-origin requests to its own internal resources (webpack HMR socket, JS chunks) unless the requesting origin is explicitly allowlisted. The initial HTML/CSS document request is same-origin-safe and rendered fine (hence the page looking fully styled), but the React bundle never properly hydrated on non-localhost origins — so the login `<form>`'s `onSubmit` handler (which calls `e.preventDefault()`) was never attached. Clicking "Sign in" fell through to the browser's native HTML form submission: a plain GET to the same URL, which looks exactly like the page silently refreshing, with no JS error to catch or display.

This explains every observed detail at once: identical failure on phone *and* a second PC (both non-localhost origins), fully-styled page (static HTML/CSS unaffected), and zero error text (the failure happened below the app's own try/catch, in Next.js's dev-server layer, not in `handleSubmit`).

---

## Fix

**`frontend/next.config.ts`**
```ts
const nextConfig: NextConfig = {
  /* config options here */
  // Allows phones/other devices on the LAN to load dev-server resources (HMR, JS chunks)
  // when testing via http://192.168.0.56:3000 instead of localhost.
  allowedDevOrigins: ["192.168.0.56"],
};
```

Frontend restarted to apply. Confirmed in `frontend_err.log` post-restart: no further "Blocked cross-origin request" warning, and `frontend_out.log` showed a successful `GET /dashboard 200` — i.e. a real login completed end-to-end from the LAN origin.

---

## Result
- Backend (`:8000`): healthy, CORS header correctly reflects `http://192.168.0.56:3000` for LAN requests.
- Worker: listening on `idp` queue, clean start.
- Frontend (`:3000`): no cross-origin blocking; login flow reaches `/dashboard` successfully from a LAN-IP origin.

## Lesson learned
When a dev server is deliberately exposed on a LAN IP for phone/multi-device testing, **three separate layers** need to agree on the non-localhost origin, not just one:
1. The frontend's own API base URL (`NEXT_PUBLIC_API_BASE_URL`) — must not hardcode `localhost`.
2. The backend's CORS allowlist (`CORS_ALLOW_ORIGINS`) — must include the LAN origin.
3. **Next.js 16+'s own dev-server cross-origin guard (`allowedDevOrigins`)** — easy to miss because it fails *silently* (no console error surfaced to the app, no network tab entry the app's own code would catch) and produces a symptom — "form just refreshes" — that looks like a native browser hiccup rather than a blocked asset. Always check `frontend_err.log`/dev-server stderr for a `Blocked cross-origin request` warning first when the page loads but interactivity silently doesn't work on a non-localhost origin.
