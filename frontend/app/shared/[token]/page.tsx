"use client";

/**
 * Public landing page for a shareable document link (no login required —
 * the token itself is the authorization). Resolves the token to a signed
 * download URL via the one deliberately unauthenticated backend endpoint,
 * GET /api/share/{token}.
 */

import { use, useEffect, useState } from "react";
import { Archive, Download, FileX, Loader2 } from "lucide-react";
import { apiResolveShare, type ResolvedShare } from "@/lib/api";

export default function SharedDocumentPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = use(params);
  const [resolved, setResolved] = useState<ResolvedShare | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    apiResolveShare(token)
      .then(setResolved)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [token]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 p-8">
      <div className="w-full max-w-sm bg-white border border-slate-200 rounded-xl p-8">
        <div className="flex items-center gap-2 mb-8 justify-center">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
            <Archive className="w-4 h-4 text-white" />
          </div>
          <span className="font-semibold text-slate-900">DataWiz Digital Archive</span>
        </div>

        {loading ? (
          <div className="flex flex-col items-center gap-3 py-6">
            <Loader2 className="w-5 h-5 animate-spin text-slate-400" />
            <p className="text-sm text-slate-500">Resolving link…</p>
          </div>
        ) : error ? (
          <div className="flex flex-col items-center gap-3 py-4 text-center">
            <FileX className="w-8 h-8 text-slate-300" />
            <p className="text-sm font-medium text-slate-700">This link isn&apos;t available</p>
            <p className="text-xs text-slate-500">{error}</p>
          </div>
        ) : resolved ? (
          <div className="text-center">
            <p className="text-sm text-slate-500 mb-1">A document was shared with you</p>
            <p className="text-sm font-medium text-slate-800 mb-6 break-words">{resolved.filename}</p>
            <a
              href={resolved.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center justify-center gap-2 w-full bg-blue-600 hover:bg-blue-700 text-white py-2.5 rounded-lg text-sm font-medium transition-colors"
            >
              <Download className="w-4 h-4" />
              Download
            </a>
          </div>
        ) : null}
      </div>
    </div>
  );
}
