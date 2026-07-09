"use client";

import { useState, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Archive, Eye, EyeOff, Loader2 } from "lucide-react";
import { supabase } from "@/lib/supabase";
import { apiBootstrap } from "@/lib/api";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [showReset, setShowReset] = useState(false);
  const [resetEmail, setResetEmail] = useState("");
  const [resetLoading, setResetLoading] = useState(false);
  const [resetSent, setResetSent] = useState(false);
  const [resetError, setResetError] = useState("");

  useEffect(() => {
    const emailParam = searchParams.get("email");
    if (emailParam) {
      setEmail(decodeURIComponent(emailParam));
    }
  }, [searchParams]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!email || !password) {
      setError("Please enter your email and password.");
      return;
    }
    setLoading(true);
    try {
      const { error: authError } = await supabase.auth.signInWithPassword({ email, password });
      if (authError) {
        setError(`Supabase auth failed: ${authError.message}`);
        return;
      }
      try {
        await apiBootstrap();
      } catch (apiErr: unknown) {
        setError(`Backend bootstrap failed: ${apiErr instanceof Error ? apiErr.message : String(apiErr)}`);
        return;
      }
      // First-time users: bootstrap just set app_metadata.tenant_id. Refresh the
      // session so the token carries tenant_id before any tenant-scoped call.
      await supabase.auth.refreshSession();
      router.push("/dashboard");
    } catch (err: unknown) {
      setError(`Supabase network error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setLoading(false);
    }
  }

  async function handleResetRequest(e: React.FormEvent) {
    e.preventDefault();
    setResetError("");
    if (!resetEmail) {
      setResetError("Please enter your email address.");
      return;
    }
    setResetLoading(true);
    try {
      const { error: resetErr } = await supabase.auth.resetPasswordForEmail(resetEmail, {
        redirectTo: `${window.location.origin}/reset-password`,
      });
      if (resetErr) {
        setResetError(resetErr.message);
        return;
      }
      setResetSent(true);
    } catch (err: unknown) {
      setResetError(err instanceof Error ? err.message : String(err));
    } finally {
      setResetLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex">
      {/* Left panel — branding */}
      <div className="hidden lg:flex flex-col justify-between w-1/2 bg-slate-900 p-12 text-white">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-blue-600 flex items-center justify-center">
            <Archive className="w-5 h-5 text-white" />
          </div>
          <div>
            <p className="font-semibold text-base leading-tight">DataWiz</p>
            <p className="text-slate-400 text-xs">Digital Archive</p>
          </div>
        </div>

        <div>
          <blockquote className="text-2xl font-light leading-relaxed text-slate-200 mb-6">
            "From mountains of paper to instant intelligence — your documents, organised and searchable in seconds."
          </blockquote>

          <div className="grid grid-cols-3 gap-4">
            {[
              { value: "1,247", label: "Documents archived" },
              { value: "94%", label: "OCR accuracy" },
              { value: "2.6 GB", label: "Storage saved" },
            ].map((s) => (
              <div key={s.label} className="bg-slate-800 rounded-lg p-4">
                <p className="text-2xl font-bold text-white">{s.value}</p>
                <p className="text-slate-400 text-xs mt-1">{s.label}</p>
              </div>
            ))}
          </div>

          <div className="mt-8 flex items-start gap-4">
            <div className="w-10 h-10 rounded-full bg-blue-700 flex items-center justify-center flex-shrink-0 text-sm font-semibold">AR</div>
            <div>
              <p className="text-sm text-slate-200">
                "We cut our invoice processing time from 3 days to 20 minutes. The AI extraction is remarkably accurate for Malaysian documents."
              </p>
              <p className="text-slate-400 text-xs mt-2">Ahmad Razif — CFO, Syarikat Maju Sdn Bhd</p>
            </div>
          </div>
        </div>

        <p className="text-slate-500 text-xs">
          PDPA-compliant • Hosted in Malaysia • ISO 27001 aligned
        </p>
      </div>

      {/* Right panel — login form */}
      <div className="flex-1 flex items-center justify-center p-8 bg-white">
        <div className="w-full max-w-sm">
          {/* Mobile logo */}
          <div className="flex items-center gap-2 mb-8 lg:hidden">
            <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
              <Archive className="w-4 h-4 text-white" />
            </div>
            <span className="font-semibold text-slate-900">DataWiz Digital Archive</span>
          </div>

          {showReset ? (
            <>
              <h1 className="text-2xl font-semibold text-slate-900 mb-1">Reset password</h1>
              <p className="text-slate-500 text-sm mb-8">
                Enter your account email and we&apos;ll send you a reset link.
              </p>

              {resetSent ? (
                <div className="text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-3.5 py-3">
                  Check <span className="font-medium">{resetEmail}</span> for a link to reset your
                  password.
                </div>
              ) : (
                <form onSubmit={handleResetRequest} className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1.5">
                      Email address
                    </label>
                    <input
                      type="email"
                      value={resetEmail}
                      onChange={(e) => setResetEmail(e.target.value)}
                      placeholder="you@company.com.my"
                      className="w-full px-3.5 py-2.5 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white text-slate-900 placeholder:text-slate-400"
                    />
                  </div>

                  {resetError && (
                    <div className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                      {resetError}
                    </div>
                  )}

                  <button
                    type="submit"
                    disabled={resetLoading}
                    className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 text-white py-2.5 rounded-lg text-sm font-medium transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
                  >
                    {resetLoading && <Loader2 className="w-4 h-4 animate-spin" />}
                    {resetLoading ? "Sending…" : "Send reset link"}
                  </button>
                </form>
              )}

              <p className="text-xs text-slate-600 text-center mt-6">
                <button
                  type="button"
                  onClick={() => {
                    setShowReset(false);
                    setResetSent(false);
                    setResetError("");
                  }}
                  className="text-blue-600 hover:text-blue-700 font-medium"
                >
                  ← Back to sign in
                </button>
              </p>
            </>
          ) : (
            <>
              <h1 className="text-2xl font-semibold text-slate-900 mb-1">Sign in</h1>
              <p className="text-slate-500 text-sm mb-8">Enter your credentials to access your archive.</p>

              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1.5">
                    Email address
                  </label>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@company.com.my"
                    className="w-full px-3.5 py-2.5 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white text-slate-900 placeholder:text-slate-400"
                  />
                </div>

                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="block text-sm font-medium text-slate-700">Password</label>
                    <button
                      type="button"
                      onClick={() => {
                        setShowReset(true);
                        setResetEmail(email);
                      }}
                      className="text-xs text-blue-600 hover:text-blue-700"
                    >
                      Forgot password?
                    </button>
                  </div>
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
                  {loading ? "Signing in…" : "Sign in"}
                </button>
              </form>
            </>
          )}

          {!showReset && (
            <p className="text-xs text-slate-600 text-center mt-6">
              Don't have an account?{" "}
              <Link href="/signup" className="text-blue-600 hover:text-blue-700 font-medium">
                Sign up
              </Link>
            </p>
          )}

          <p className="text-xs text-slate-400 text-center mt-8">
            © 2026 DataWiz. PDPA-compliant document processing.
          </p>
        </div>
      </div>
    </div>
  );
}

/**
 * Next 16 requires any `useSearchParams()` consumer to sit under a Suspense
 * boundary, otherwise the route de-opts to full client rendering (and the build
 * errors). Wrapping the form keeps the page stable.
 */
export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
