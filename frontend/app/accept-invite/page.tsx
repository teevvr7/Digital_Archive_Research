"use client";

/**
 * Landing page for the Supabase invite email link (auth/service.py::invite_user's
 * `redirect_to`). Supabase's client auto-exchanges the invite token in the URL
 * fragment for a session and fires SIGNED_IN (no dedicated "invited" event exists,
 * unlike PASSWORD_RECOVERY for reset links — see reset-password/page.tsx). We wait
 * for that (or an already-established session, in case the event fired before we
 * subscribed), then let the user set their password. `app_metadata.tenant_id`/`role`
 * were already set by the backend at invite time, so the session this page ends up
 * with is already fully scoped — we bootstrap (idempotent) and go straight in,
 * unlike reset-password which signs out and sends the user back to /login.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Archive, Eye, EyeOff, Loader2 } from "lucide-react";
import { supabase } from "@/lib/supabase";
import { apiBootstrap } from "@/lib/api";

export default function AcceptInvitePage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [checking, setChecking] = useState(true);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((event) => {
      if (event === "SIGNED_IN") {
        setReady(true);
        setChecking(false);
      }
    });

    supabase.auth.getSession().then(({ data }) => {
      if (data.session) setReady(true);
      setChecking(false);
    });

    return () => subscription.unsubscribe();
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    setLoading(true);
    try {
      const { error: updateErr } = await supabase.auth.updateUser({ password });
      if (updateErr) {
        setError(updateErr.message);
        return;
      }
      try {
        await apiBootstrap();
      } catch (apiErr: unknown) {
        setError(`Backend sync failed: ${apiErr instanceof Error ? apiErr.message : String(apiErr)}`);
        return;
      }
      await supabase.auth.refreshSession();
      router.push("/dashboard");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 p-8">
      <div className="w-full max-w-sm bg-white border border-slate-200 rounded-xl p-8">
        <div className="flex items-center gap-2 mb-8 justify-center">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
            <Archive className="w-4 h-4 text-white" />
          </div>
          <span className="font-semibold text-slate-900">DataWiz Digital Archive</span>
        </div>

        {checking ? (
          <p className="text-sm text-slate-500 text-center py-4">Verifying invite…</p>
        ) : !ready ? (
          <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3.5 py-3 text-center">
            This invite link is invalid or has expired. Ask a teammate to send you a new one.
          </div>
        ) : (
          <>
            <h1 className="text-xl font-semibold text-slate-900 mb-1 text-center">
              Welcome — set your password
            </h1>
            <p className="text-slate-500 text-sm mb-6 text-center">
              Choose a password to finish joining your team&apos;s archive.
            </p>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1.5">
                  Password
                </label>
                <div className="relative">
                  <input
                    type={showPw ? "text" : "password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    className="w-full px-3.5 py-2.5 pr-10 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white text-slate-900 placeholder:text-slate-400"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPw((v) => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                  >
                    {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1.5">
                  Confirm password
                </label>
                <input
                  type={showPw ? "text" : "password"}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full px-3.5 py-2.5 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white text-slate-900 placeholder:text-slate-400"
                />
              </div>

              {error && (
                <div className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 text-white py-2.5 rounded-lg text-sm font-medium transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {loading && <Loader2 className="w-4 h-4 animate-spin" />}
                {loading ? "Joining…" : "Join workspace"}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
