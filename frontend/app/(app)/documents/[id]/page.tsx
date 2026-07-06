"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Download,
  RefreshCw,
  FileScan,
  CheckCircle2,
  AlertCircle,
  Clock,
  ChevronDown,
  ChevronRight,
  Copy,
  Check,
  Loader2,
} from "lucide-react";
import { StatusBadge } from "@/components/status-badge";
import { formatBytes, formatRelativeTime } from "@/lib/format";
import {
  apiDocument,
  apiDownloadUrl,
  apiExtractDocument,
  apiRetryDocument,
  apiReprocessDocument,
  apiListIDPConfigs,
  apiListTemplates,
  type Template,
} from "@/lib/api";
import type { Document } from "@/types";

function JsonValue({ value, depth = 0 }: { value: unknown; depth?: number }) {
  const [open, setOpen] = useState(depth < 2);

  if (Array.isArray(value)) {
    return (
      <span>
        <button
          onClick={() => setOpen((v) => !v)}
          className="text-slate-400 hover:text-slate-600 inline-flex items-center gap-0.5"
        >
          {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          <span className="text-slate-500 text-xs">[{value.length}]</span>
        </button>
        {open && (
          <div className="ml-4 border-l border-slate-100 pl-3 mt-1 space-y-1">
            {value.map((item, i) => (
              <div key={i} className="flex items-start gap-1">
                <span className="text-slate-400 text-xs">{i}:</span>
                <JsonValue value={item} depth={depth + 1} />
              </div>
            ))}
          </div>
        )}
      </span>
    );
  }

  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    return (
      <span>
        <button
          onClick={() => setOpen((v) => !v)}
          className="text-slate-400 hover:text-slate-600 inline-flex items-center gap-0.5"
        >
          {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          <span className="text-slate-500 text-xs">{`{${entries.length}}`}</span>
        </button>
        {open && (
          <div className="ml-4 border-l border-slate-100 pl-3 mt-1 space-y-1">
            {entries.map(([k, v]) => (
              <div key={k} className="flex items-start gap-1.5">
                <span className="text-blue-700 text-xs font-mono flex-shrink-0">{k}:</span>
                <JsonValue value={v} depth={depth + 1} />
              </div>
            ))}
          </div>
        )}
      </span>
    );
  }

  if (typeof value === "string")
    return <span className="text-green-700 text-xs font-mono">"{value}"</span>;
  if (typeof value === "number")
    return <span className="text-orange-600 text-xs font-mono">{value}</span>;
  if (typeof value === "boolean")
    return <span className="text-violet-700 text-xs font-mono">{String(value)}</span>;
  return <span className="text-slate-500 text-xs font-mono">null</span>;
}

export default function DocumentViewerPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [doc, setDoc] = useState<Document | null>(null);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [copied, setCopied] = useState(false);
  const [activeTab, setActiveTab] = useState<"extracted" | "metadata" | "raw">(
    "extracted"
  );
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [configs, setConfigs] = useState<any[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);
  const [reprocessing, setReprocessing] = useState(false);

  useEffect(() => {
    Promise.all([apiListIDPConfigs(), apiListTemplates()])
      .then(([configRes, templateRes]) => {
        setConfigs(configRes.configs);
        setTemplates(templateRes);
      })
      .catch((e) => console.error("Failed to load configs/templates:", e));
  }, []);

  useEffect(() => {
    if (doc) {
      setSelectedTemplateId(doc.templateId || "");
    }
  }, [doc]);

  useEffect(() => {
    apiDocument(id)
      .then(setDoc)
      .catch((e: unknown) =>
        setLoadError(e instanceof Error ? e.message : String(e))
      );
  }, [id]);

  // Poll while the document is still processing; stops at completed/failed.
  useEffect(() => {
    if (!doc || doc.status === "completed" || doc.status === "failed") return;

    const timerId = setInterval(() => {
      apiDocument(id).then(setDoc).catch(() => {});
    }, 3000);

    return () => clearInterval(timerId);
  }, [id, doc?.status]);

  // Fetch signed URL for inline preview once the doc is loaded.
  useEffect(() => {
    if (!doc) return;
    apiDownloadUrl(doc.id)
      .then(({ url }) => setPreviewUrl(url))
      .catch(() => {}); // preview is best-effort; user can still click Download
  }, [doc?.id]);

  const handleDownload = async () => {
    if (!doc) return;
    setActionError("");
    try {
      const { url } = await apiDownloadUrl(doc.id);
      window.open(url, "_blank");
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : "Download failed");
    }
  };

  const handleRetry = async () => {
    if (!doc) return;
    setActionError("");
    try {
      const updated = await apiRetryDocument(doc.id);
      setDoc(updated);
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : "Retry failed");
    }
  };

  const handleExtract = async () => {
    if (!doc) return;
    setActionError("");
    try {
      const updated = await apiExtractDocument(doc.id);
      setDoc(updated);
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : "Extraction request failed");
    }
  };

  const handleReprocess = async () => {
    if (!doc) return;
    setActionError("");
    setReprocessing(true);
    try {
      const updated = await apiReprocessDocument(doc.id, selectedTemplateId || null);
      setDoc(updated);
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : "Reprocessing failed");
    } finally {
      setReprocessing(false);
    }
  };

  const handleCopy = () => {
    if (doc?.extractedData) {
      navigator.clipboard.writeText(JSON.stringify(doc.extractedData, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  if (loadError) {
    return (
      <div className="p-8 text-center">
        <p className="text-red-500 text-sm">{loadError}</p>
        <Link href="/documents" className="text-blue-600 text-sm mt-2 inline-block">
          ← Back to documents
        </Link>
      </div>
    );
  }

  if (!doc) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Top bar */}
      <div className="px-6 py-4 bg-white border-b border-slate-200 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-4">
          <Link
            href="/documents"
            className="flex items-center gap-1.5 text-slate-500 hover:text-slate-700 text-sm transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Documents
          </Link>
          <span className="text-slate-300">/</span>
          <span className="text-slate-700 text-sm font-medium truncate max-w-xs">
            {doc.originalFilename}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={doc.status} />
          {actionError && (
            <span className="text-xs text-red-500">{actionError}</span>
          )}
          {doc.status === "failed" && (
            <button
              onClick={handleRetry}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-slate-200 rounded-lg hover:bg-slate-50 text-slate-600 transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Retry
            </button>
          )}
          <button
            onClick={handleDownload}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
          >
            <Download className="w-3.5 h-3.5" />
            Download
          </button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Document preview panel */}
        <div className="flex-1 bg-slate-100 flex flex-col items-center justify-center border-r border-slate-200 overflow-hidden">
          <div className="w-full h-full flex items-center justify-center">
            {doc.mimeType.startsWith("image/") ? (
              previewUrl ? (
                <img
                  src={previewUrl}
                  alt={doc.originalFilename}
                  className="max-w-full max-h-full object-contain rounded-lg shadow-lg"
                />
              ) : (
                <div className="flex flex-col items-center gap-2">
                  <Loader2 className="w-6 h-6 text-slate-400 animate-spin" />
                  <p className="text-xs text-slate-400">Loading preview…</p>
                </div>
              )
            ) : previewUrl ? (
              <iframe
                src={previewUrl}
                className="w-full h-full border-0"
                title={doc.originalFilename}
              />
            ) : (
              <div className="flex flex-col items-center gap-2">
                <Loader2 className="w-6 h-6 text-slate-400 animate-spin" />
                <p className="text-xs text-slate-400">Loading preview…</p>
              </div>
            )}
          </div>

          {/* Processing info bar */}
          <div className="w-full px-6 py-3 bg-white border-t border-slate-200 flex items-center gap-4 text-xs text-slate-500 flex-shrink-0">
            <span className="flex items-center gap-1.5">
              {doc.hasTextLayer ? (
                <>
                  <CheckCircle2 className="w-3.5 h-3.5 text-green-500" /> Text layer
                  detected (OCR skipped)
                </>
              ) : (
                <>
                  <FileScan className="w-3.5 h-3.5 text-blue-500" /> Scanned document —
                  OCR used
                </>
              )}
            </span>
            {doc.processedAt && (
              <span className="flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5" />
                Processed {formatRelativeTime(doc.processedAt)}
              </span>
            )}
            <span>{formatBytes(doc.sizeBytes)}</span>
          </div>
        </div>

        {/* Right panel — extracted data */}
        <div className="w-96 flex flex-col bg-white flex-shrink-0 overflow-hidden">
          {/* Tabs */}
          <div className="border-b border-slate-200 flex flex-shrink-0">
            {(["extracted", "metadata", "raw"] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`flex-1 py-3 text-xs font-medium capitalize transition-colors ${
                  activeTab === tab
                    ? "border-b-2 border-blue-600 text-blue-700"
                    : "text-slate-500 hover:text-slate-700"
                }`}
              >
                {tab === "extracted"
                  ? "Extracted Data"
                  : tab === "metadata"
                  ? "Metadata"
                  : "Raw JSON"}
              </button>
            ))}
          </div>

          <div className="flex-1 overflow-y-auto p-4">
            {activeTab === "extracted" && (
              <>
                {/* Template override select & reprocess */}
                {(() => {
                  const docTypeConfig = configs.find((c) => c.name.toLowerCase() === doc.documentType.toLowerCase());
                  const matchingTemplates = docTypeConfig
                    ? templates.filter((t) => t.documentTypeId === docTypeConfig.documentTypeId)
                    : [];

                  return (
                    <div className="bg-slate-50 border border-slate-100 rounded-lg p-3 mb-4 space-y-2">
                      <label className="block text-[10px] font-semibold text-slate-500 uppercase tracking-wide">
                        Extraction Template Layout
                      </label>
                      <div className="flex gap-2">
                        <div className="relative flex-1">
                          <select
                            value={selectedTemplateId || ""}
                            onChange={(e) => setSelectedTemplateId(e.target.value)}
                            className="w-full appearance-none text-xs pl-2.5 pr-8 py-2 rounded-lg border border-slate-200 bg-white text-slate-700 cursor-pointer focus:outline-none focus:ring-1 focus:ring-blue-500 font-medium"
                          >
                            <option value="">Default Strategy</option>
                            {matchingTemplates.map((t) => (
                              <option key={t.id} value={t.id}>
                                {t.name} {t.isDefault ? "(Default)" : ""}
                              </option>
                            ))}
                          </select>
                          <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
                        </div>
                        <button
                          onClick={handleReprocess}
                          disabled={reprocessing}
                          className="px-3.5 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-lg text-xs font-semibold transition-colors flex items-center gap-1.5 cursor-pointer"
                        >
                          {reprocessing ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <RefreshCw className="w-3.5 h-3.5" />
                          )}
                          Reprocess
                        </button>
                      </div>
                    </div>
                  );
                })()}

                {doc.extractedData ? (
                  <div className="space-y-3">
                    {doc.confidence != null && (
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs text-slate-400 capitalize">{doc.documentType}</span>
                        <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${doc.confidence >= 0.7 ? "bg-green-100 text-green-700" : "bg-yellow-100 text-yellow-700"}`}>
                          {Math.round(doc.confidence * 100)}% confident
                        </span>
                      </div>
                    )}
                    {Object.entries(doc.extractedData).map(([key, value]) => {
                      if (Array.isArray(value)) {
                        return (
                          <div key={key} className="bg-slate-50 rounded-lg p-3">
                            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                              {key.replace(/([A-Z])/g, " $1").replace(/_/g, " ").trim()}
                            </p>
                            <div className="space-y-2">
                              {(value as Record<string, unknown>[]).map((item, i) => (
                                <div
                                  key={i}
                                  className="bg-white border border-slate-200 rounded p-2 text-xs space-y-1"
                                >
                                  {Object.entries(item).map(([k, v]) => (
                                    <div key={k} className="flex items-center justify-between gap-2">
                                      <span className="text-slate-400 capitalize">
                                        {k.replace(/([A-Z])/g, " $1").replace(/_/g, " ")}
                                      </span>
                                      <span className="font-medium text-slate-700 text-right">
                                        {String(v)}
                                      </span>
                                    </div>
                                  ))}
                                </div>
                              ))}
                            </div>
                          </div>
                        );
                      }

                      // Render nested objects (e.g. vendor_details, financials) inside cards
                      if (typeof value === "object" && value !== null) {
                        return (
                          <div key={key} className="bg-slate-50 rounded-lg p-3 border border-slate-100">
                            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                              {key.replace(/([A-Z])/g, " $1").replace(/_/g, " ").trim()}
                            </p>
                            <div className="space-y-1.5">
                              {Object.entries(value as Record<string, unknown>).map(([k, v]) => (
                                <div
                                  key={k}
                                  className="flex items-start justify-between gap-3 py-1 border-b border-slate-100 last:border-b-0"
                                >
                                  <span className="text-xs text-slate-400 capitalize">
                                    {k.replace(/([A-Z])/g, " $1").replace(/_/g, " ").trim()}
                                  </span>
                                  <span className="text-xs font-medium text-slate-700 text-right">
                                    {typeof v === "number" && k.toLowerCase().includes("amount")
                                      ? `MYR ${(v as number).toFixed(2)}`
                                      : String(v)}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>
                        );
                      }

                      return (
                        <div
                          key={key}
                          className="flex items-start justify-between gap-3 py-2 border-b border-slate-50"
                        >
                          <span className="text-xs text-slate-500 capitalize flex-shrink-0">
                            {key.replace(/([A-Z])/g, " $1").replace(/_/g, " ").trim()}
                          </span>
                          <span className="text-xs font-semibold text-slate-800 text-right">
                            {typeof value === "number" &&
                            key.toLowerCase().includes("amount")
                              ? `MYR ${(value as number).toFixed(2)}`
                              : String(value)}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                ) : doc.extractedText ? (
                  <div className="space-y-2">
                    <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
                      Extracted Text
                    </p>
                    <pre className="text-xs text-slate-700 whitespace-pre-wrap leading-relaxed bg-slate-50 rounded-lg p-3 max-h-[28rem] overflow-y-auto">
                      {doc.extractedText}
                    </pre>
                    <div className="flex items-center justify-between">
                      <p className="text-xs text-slate-400">
                        Structured data extraction (AI) has not run yet.
                      </p>
                      <button
                        onClick={handleExtract}
                        className="text-xs text-blue-600 hover:underline flex items-center gap-1"
                      >
                        <FileScan className="w-3 h-3" /> Re-run AI extraction
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center h-32 text-center">
                    {[
                      "queued",
                      "extracting_text",
                      "ocr_processing",
                      "ai_extraction",
                    ].includes(doc.status) ? (
                      <>
                        <Clock className="w-8 h-8 text-slate-300 mb-2" />
                        <p className="text-slate-400 text-sm">Extraction in progress…</p>
                        <p className="text-slate-400 text-xs mt-1">Check back shortly</p>
                      </>
                    ) : (
                      <>
                        <AlertCircle className="w-8 h-8 text-red-300 mb-2" />
                        <p className="text-slate-400 text-sm">Extraction failed</p>
                        <button
                          onClick={handleRetry}
                          className="mt-2 text-xs text-blue-600 hover:underline flex items-center gap-1"
                        >
                          <RefreshCw className="w-3 h-3" /> Retry processing
                        </button>
                      </>
                    )}
                  </div>
                )}
              </>
            )}

            {activeTab === "metadata" && (
              <div className="space-y-2">
                {[
                  ["Document ID", doc.id],
                  ["Original filename", doc.originalFilename],
                  ["Type", doc.documentType],
                  ["MIME type", doc.mimeType],
                  ["Size", formatBytes(doc.sizeBytes)],
                  ["Pages", doc.pageCount ?? "—"],
                  ["Has text layer", doc.hasTextLayer ? "Yes" : "No"],
                  [
                    "OCR confidence",
                    doc.ocrConfidence
                      ? `${Math.round(doc.ocrConfidence * 100)}%`
                      : "—",
                  ],
                  [
                    "AI confidence",
                    doc.confidence != null
                      ? `${Math.round(doc.confidence * 100)}%`
                      : "—",
                  ],
                  ["Uploaded by", doc.uploadedBy],
                  ["Uploaded at", new Date(doc.uploadedAt).toLocaleString("en-MY")],
                  [
                    "Processed at",
                    doc.processedAt
                      ? new Date(doc.processedAt).toLocaleString("en-MY")
                      : "—",
                  ],
                  ["Tags", doc.tags.join(", ") || "—"],
                  ["Storage key", doc.storageKey],
                ].map(([label, val]) => (
                  <div
                    key={String(label)}
                    className="flex items-start justify-between gap-3 py-2 border-b border-slate-50"
                  >
                    <span className="text-xs text-slate-500 flex-shrink-0">{label}</span>
                    <span className="text-xs font-medium text-slate-700 text-right break-all">
                      {String(val)}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {activeTab === "raw" && (
              <div className="relative">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
                    Extracted JSON
                  </span>
                  <button
                    onClick={handleCopy}
                    className="flex items-center gap-1 px-2 py-1 rounded border border-slate-200 hover:bg-slate-50 text-slate-500 text-xs transition-colors"
                  >
                    {copied ? (
                      <Check className="w-3 h-3 text-green-600" />
                    ) : (
                      <Copy className="w-3 h-3" />
                    )}
                    {copied ? "Copied" : "Copy"}
                  </button>
                </div>
                {doc.extractedData ? (
                  <div className="bg-slate-50 rounded-lg p-3 font-mono text-xs leading-relaxed">
                    <JsonValue value={doc.extractedData} />
                  </div>
                ) : (
                  <div className="bg-slate-50 rounded-lg p-4 text-center">
                    <p className="text-slate-400 text-xs">No extracted data yet.</p>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Tags footer */}
          <div className="px-4 py-3 border-t border-slate-100 flex-shrink-0">
            <p className="text-xs text-slate-400 mb-2">Tags</p>
            <div className="flex flex-wrap gap-1.5">
              {doc.tags.map((tag) => (
                <span
                  key={tag}
                  className="px-2 py-0.5 bg-slate-100 text-slate-600 rounded text-xs"
                >
                  {tag}
                </span>
              ))}
              <button className="px-2 py-0.5 border border-dashed border-slate-300 text-slate-400 rounded text-xs hover:border-blue-400 hover:text-blue-600 transition-colors">
                + Add tag
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
