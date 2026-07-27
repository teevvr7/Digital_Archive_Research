"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Archive, Eye, EyeOff, Loader2 } from "lucide-react";
import { supabase } from "@/lib/supabase";
import { apiBootstrap, apiSignup } from "@/lib/api";

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    if (!email || !password || !confirmPassword) {
      setError("Please fill in all fields.");
      return;
    }

    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    if (password.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }

    setLoading(true);
    try {
      // 1. Create the (pre-confirmed) account via the backend admin endpoint.
      await apiSignup(email, password);

      // 2. Sign in against Supabase to obtain a session/access token.
      const { error: signInError } = await supabase.auth.signInWithPassword({ email, password });
      if (signInError) {
        // Account exists but auto sign-in failed — send them to login pre-filled.
        router.push(`/login?email=${encodeURIComponent(email)}`);
        return;
      }

      // 3. Provision the tenant/user rows on the backend (idempotent). This sets
      //    app_metadata.tenant_id on the Supabase user server-side.
      await apiBootstrap();

      // 4. Refresh the session so the new access token carries the tenant_id claim
      //    — without this, every tenant-scoped API call would 403.
      await supabase.auth.refreshSession();

      router.push("/dashboard");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
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
            &quot;From mountains of paper to instant intelligence — your documents, organised and searchable in seconds.&quot;
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
                &quot;We cut our invoice processing time from 3 days to 20 minutes. The AI extraction is remarkably accurate for Malaysian documents.&quot;
              </p>
              <p className="text-slate-400 text-xs mt-2">Ahmad Razif — CFO, Syarikat Maju Sdn Bhd</p>
            </div>
          </div>
        </div>

        <p className="text-slate-500 text-xs">
          PDPA-compliant • Hosted in Malaysia • ISO 27001 aligned
        </p>
      </div>

      {/* Right panel — signup form */}
      <div className="flex-1 flex items-center justify-center p-8 bg-white">
        <div className="w-full max-w-sm">
          {/* Mobile logo */}
          <div className="flex items-center gap-2 mb-8 lg:hidden">
            <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
              <Archive className="w-4 h-4 text-white" />
            </div>
            <span className="font-semibold text-slate-900">DataWiz Digital Archive</span>
          </div>

          <h1 className="text-2xl font-semibold text-slate-900 mb-1">Create account</h1>
          <p className="text-slate-500 text-sm mb-8">Sign up to start organizing your documents.</p>

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
              <label className="block text-sm font-medium text-slate-700 mb-1.5">Password</label>
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
              <label className="block text-sm font-medium text-slate-700 mb-1.5">Confirm password</label>
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
              {loading ? "Creating account…" : "Create account"}
            </button>
          </form>

          <p className="text-xs text-slate-600 text-center mt-6">
            Already have an account?{" "}
            <Link href="/login" className="text-blue-600 hover:text-blue-700 font-medium">
              Sign in
            </Link>
          </p>

          <p className="text-xs text-slate-400 text-center mt-8">
            © 2026 DataWiz. PDPA-compliant document processing.
          </p>
        </div>
      </div>
    </div>
  );
}
