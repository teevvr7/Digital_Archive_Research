"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Download,
  RefreshCw,
  FileScan,
  FileX,
  CheckCircle2,
  AlertCircle,
  Clock,
  ChevronDown,
  ChevronRight,
  Copy,
  Check,
  Loader2,
  Trash2,
  RotateCcw,
  Pencil,
  X,
  Save,
  Plus,
} from "lucide-react";
import { StatusBadge } from "@/components/status-badge";
import { formatBytes, formatRelativeTime } from "@/lib/format";
import {
  apiDocument,
  apiDownloadUrl,
  apiExtractDocument,
  apiRetryDocument,
  apiPatchDocument,
  apiTrashDocument,
  apiRestoreDocument,
  apiTags,
  apiAssignTag,
  apiUnassignTag,
  type DocumentPatch,
} from "@/lib/api";
import type { Document, DocumentType, Tag } from "@/types";

const NON_RENDERABLE_MIMES = new Set([
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "message/rfc822",
]);

const TEXT_MIMES = new Set(["text/plain", "text/csv", "text/markdown"]);

const ALL_TYPES: DocumentType[] = [
  "invoice", "receipt", "contract", "report", "letter", "form", "other",
];

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
  const [activeTab, setActiveTab] = useState<"extracted" | "metadata" | "raw">("extracted");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [textContent, setTextContent] = useState<string | null>(null);

  // Edit mode state
  const [editing, setEditing] = useState(false);
  const [editDraft, setEditDraft] = useState<{
    title: string;
    documentType: DocumentType;
    documentDate: string;
  }>({ title: "", documentType: "other", documentDate: "" });
  const [saving, setSaving] = useState(false);

  // Tag management state
  const [allTags, setAllTags] = useState<Tag[]>([]);
  const [showTagPicker, setShowTagPicker] = useState(false);

  useEffect(() => {
    apiTags().then(setAllTags).catch(() => {});
  }, []);

  useEffect(() => {
    apiDocument(id)
      .then(setDoc)
      .catch((e: unknown) =>
        setLoadError(e instanceof Error ? e.message : String(e))
      );
  }, [id]);

  // Poll while the document is still processing; stops at terminal states.
  useEffect(() => {
    if (!doc || doc.status === "completed" || doc.status === "failed" || doc.status === "needs_review") return;

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
      .catch(() => {});
  }, [doc?.id]);

  // For text/csv/md files, fetch the actual text content via the signed URL.
  useEffect(() => {
    if (!doc || !previewUrl || !TEXT_MIMES.has(doc.mimeType)) return;
    fetch(previewUrl)
      .then((r) => r.text())
      .then(setTextContent)
      .catch(() => {});
  }, [doc?.mimeType, previewUrl]);

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

  const handleCopy = () => {
    if (doc?.extractedData) {
      navigator.clipboard.writeText(JSON.stringify(doc.extractedData, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const openEditMode = () => {
    if (!doc) return;
    setEditDraft({
      title: doc.title,
      documentType: doc.documentType,
      documentDate: doc.documentDate
        ? new Date(doc.documentDate).toISOString().split("T")[0]
        : "",
    });
    setEditing(true);
    setActiveTab("metadata");
  };

  const handleSave = async () => {
    if (!doc) return;
    setSaving(true);
    setActionError("");
    try {
      const patch: DocumentPatch = {
        title: editDraft.title || undefined,
        documentType: editDraft.documentType || undefined,
        documentDate: editDraft.documentDate || null,
      };
      const updated = await apiPatchDocument(doc.id, patch);
      setDoc(updated);
      setEditing(false);
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleTrash = async () => {
    if (!doc) return;
    setActionError("");
    try {
      const updated = await apiTrashDocument(doc.id);
      setDoc(updated);
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : "Move to trash failed");
    }
  };

  const handleRestore = async () => {
    if (!doc) return;
    setActionError("");
    try {
      const updated = await apiRestoreDocument(doc.id);
      setDoc(updated);
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : "Restore failed");
    }
  };

  const handleAssignTag = async (tagId: string) => {
    if (!doc) return;
    try {
      await apiAssignTag(doc.id, tagId);
      const refreshed = await apiDocument(doc.id);
      setDoc(refreshed);
      setShowTagPicker(false);
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : "Failed to assign tag");
    }
  };

  const handleUnassignTag = async (tagId: string) => {
    if (!doc) return;
    try {
      await apiUnassignTag(doc.id, tagId);
      const refreshed = await apiDocument(doc.id);
      setDoc(refreshed);
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : "Failed to remove tag");
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

  const isTrashed = doc.deletedAt != null;

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
            {doc.title || doc.originalFilename}
          </span>
          {isTrashed && (
            <span className="px-2 py-0.5 bg-red-100 text-red-600 rounded text-xs font-medium">
              In trash
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={doc.status} />
          {actionError && (
            <span className="text-xs text-red-500">{actionError}</span>
          )}
          {!editing && !isTrashed && (
            <button
              onClick={openEditMode}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-slate-200 rounded-lg hover:bg-slate-50 text-slate-600 transition-colors"
            >
              <Pencil className="w-3.5 h-3.5" />
              Edit
            </button>
          )}
          {doc.status === "failed" && !isTrashed && (
            <button
              onClick={handleRetry}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-slate-200 rounded-lg hover:bg-slate-50 text-slate-600 transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Retry
            </button>
          )}
          {isTrashed ? (
            <button
              onClick={handleRestore}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-green-300 rounded-lg hover:bg-green-50 text-green-700 transition-colors"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Restore
            </button>
          ) : (
            <button
              onClick={handleTrash}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-red-200 rounded-lg hover:bg-red-50 text-red-600 transition-colors"
              title="Move to trash"
            >
              <Trash2 className="w-3.5 h-3.5" />
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
            {TEXT_MIMES.has(doc.mimeType) ? (
              textContent != null ? (
                <pre className="w-full h-full p-6 text-xs text-slate-700 font-mono leading-relaxed whitespace-pre-wrap overflow-auto bg-white">
                  {textContent}
                </pre>
              ) : (
                <div className="flex flex-col items-center gap-2">
                  <Loader2 className="w-6 h-6 text-slate-400 animate-spin" />
                  <p className="text-xs text-slate-400">Loading content…</p>
                </div>
              )
            ) : doc.mimeType.startsWith("image/") ? (
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
            ) : NON_RENDERABLE_MIMES.has(doc.mimeType) ? (
              <div className="flex flex-col items-center gap-3 text-center px-6">
                <FileX className="w-10 h-10 text-slate-300" />
                <p className="text-sm text-slate-500">
                  No inline preview for this file type yet.
                </p>
                <button
                  onClick={handleDownload}
                  className="text-xs text-blue-600 hover:underline"
                >
                  Download to view
                </button>
              </div>
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

        {/* Right panel */}
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
                              {key.replace(/([A-Z])/g, " $1").trim()}
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
                                        {k.replace(/([A-Z])/g, " $1")}
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
                      return (
                        <div
                          key={key}
                          className="flex items-start justify-between gap-3 py-2 border-b border-slate-50"
                        >
                          <span className="text-xs text-slate-500 capitalize flex-shrink-0">
                            {key.replace(/([A-Z])/g, " $1").trim()}
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
                    {["queued", "extracting_text", "ocr_processing", "ai_extraction"].includes(doc.status) ? (
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
              <div className="space-y-3">
                {editing ? (
                  /* ---- Edit form ---- */
                  <div className="space-y-3">
                    <div>
                      <label className="text-xs text-slate-500 block mb-1">Title</label>
                      <input
                        value={editDraft.title}
                        onChange={(e) => setEditDraft((d) => ({ ...d, title: e.target.value }))}
                        className="w-full px-2 py-1.5 rounded border border-slate-200 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>
                    <div>
                      <label className="text-xs text-slate-500 block mb-1">Type</label>
                      <select
                        value={editDraft.documentType}
                        onChange={(e) =>
                          setEditDraft((d) => ({ ...d, documentType: e.target.value as DocumentType }))
                        }
                        className="w-full px-2 py-1.5 rounded border border-slate-200 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                      >
                        {ALL_TYPES.map((t) => (
                          <option key={t} value={t}>
                            {t.charAt(0).toUpperCase() + t.slice(1)}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="text-xs text-slate-500 block mb-1">Document date</label>
                      <input
                        type="date"
                        value={editDraft.documentDate}
                        onChange={(e) => setEditDraft((d) => ({ ...d, documentDate: e.target.value }))}
                        className="w-full px-2 py-1.5 rounded border border-slate-200 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>
                    <div className="flex gap-2 pt-1">
                      <button
                        onClick={handleSave}
                        disabled={saving}
                        className="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-xs rounded-lg transition-colors"
                      >
                        {saving ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <Save className="w-3.5 h-3.5" />
                        )}
                        Save
                      </button>
                      <button
                        onClick={() => setEditing(false)}
                        disabled={saving}
                        className="flex items-center justify-center gap-1.5 px-3 py-1.5 border border-slate-200 hover:bg-slate-50 text-slate-600 text-xs rounded-lg transition-colors"
                      >
                        <X className="w-3.5 h-3.5" />
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  /* ---- View mode ---- */
                  <div className="space-y-2">
                    {[
                      ["Document ID", doc.id],
                      ["Title", doc.title],
                      ["Original filename", doc.originalFilename],
                      ["Type", doc.documentType],
                      ["MIME type", doc.mimeType],
                      ["Size", formatBytes(doc.sizeBytes)],
                      [
                        "Document date",
                        doc.documentDate
                          ? new Date(doc.documentDate).toLocaleDateString("en-MY")
                          : "—",
                      ],
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
                      [
                        "In trash since",
                        doc.deletedAt
                          ? new Date(doc.deletedAt).toLocaleString("en-MY")
                          : "—",
                      ],
                      ["Correspondent", doc.correspondent?.name ?? "—"],
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
            <div className="flex flex-wrap gap-1.5 relative">
              {doc.tags.map((tag) => (
                <span
                  key={tag.id}
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium"
                  style={{ background: tag.color + "22", color: tag.color }}
                >
                  {tag.name}
                  <button
                    onClick={() => handleUnassignTag(tag.id)}
                    className="opacity-60 hover:opacity-100"
                    title="Remove tag"
                  >
                    <X className="w-2.5 h-2.5" />
                  </button>
                </span>
              ))}
              <div className="relative">
                <button
                  onClick={() => setShowTagPicker((v) => !v)}
                  className="px-2 py-0.5 border border-dashed border-slate-300 text-slate-400 rounded text-xs hover:border-blue-400 hover:text-blue-600 transition-colors inline-flex items-center gap-1"
                >
                  <Plus className="w-3 h-3" /> Add
                </button>
                {showTagPicker && allTags.length > 0 && (
                  <div className="absolute bottom-full mb-1 left-0 bg-white border border-slate-200 rounded-lg shadow-lg py-1 z-10 min-w-32 max-h-40 overflow-y-auto">
                    {allTags
                      .filter((t) => !doc.tags.some((dt) => dt.id === t.id))
                      .map((t) => (
                        <button
                          key={t.id}
                          onClick={() => handleAssignTag(t.id)}
                          className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-slate-50 text-xs text-left"
                        >
                          <span
                            className="w-2 h-2 rounded-full flex-shrink-0"
                            style={{ background: t.color }}
                          />
                          {t.name}
                        </button>
                      ))}
                    {allTags.filter((t) => !doc.tags.some((dt) => dt.id === t.id)).length === 0 && (
                      <p className="px-3 py-2 text-xs text-slate-400">All tags assigned</p>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
