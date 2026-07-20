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
  Share2,
} from "lucide-react";
import { StatusBadge } from "@/components/status-badge";
import { ActivityIcon, ActivityLabel } from "@/components/activity-item";
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
  apiCustomFields,
  apiSetFieldValue,
  apiDeleteFieldValue,
  apiPredefinedFields,
  apiCorrespondents,
  apiActivity,
  apiCreateShare,
  apiListShares,
  apiRevokeShare,
  type DocumentPatch,
  type ActivityListResponse,
  type DocumentShare,
} from "@/lib/api";
import { CustomFieldInput, parseCustomFieldValue } from "@/components/custom-field-input";
import type {
  CustomField,
  Correspondent,
  Document,
  DocumentType,
  FieldValue,
  PredefinedField,
  Tag,
} from "@/types";

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
  const [activeTab, setActiveTab] = useState<"extracted" | "metadata" | "raw" | "history">("extracted");
  const [history, setHistory] = useState<ActivityListResponse | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [textContent, setTextContent] = useState<string | null>(null);

  // Share modal state
  const [showShareModal, setShowShareModal] = useState(false);
  const [shares, setShares] = useState<DocumentShare[]>([]);
  const [sharesLoading, setSharesLoading] = useState(false);
  const [creatingShare, setCreatingShare] = useState(false);
  const [newShareDays, setNewShareDays] = useState(7);
  const [copiedShareId, setCopiedShareId] = useState<string | null>(null);

  // Edit mode state
  const [editing, setEditing] = useState(false);
  const [editDraft, setEditDraft] = useState<{
    title: string;
    documentType: DocumentType;
    documentDate: string;
    correspondentId: string;
  }>({ title: "", documentType: "other", documentDate: "", correspondentId: "" });
  const [saving, setSaving] = useState(false);

  // Tag management state
  const [allTags, setAllTags] = useState<Tag[]>([]);
  const [showTagPicker, setShowTagPicker] = useState(false);

  // Correspondent picker state
  const [allCorrespondents, setAllCorrespondents] = useState<Correspondent[]>([]);

  // Extraction correction state
  const [extractionEditing, setExtractionEditing] = useState(false);
  const [extractionDraft, setExtractionDraft] = useState<Record<string, string>>({});
  const [savingExtraction, setSavingExtraction] = useState(false);

  // Custom field state
  const [allCustomFields, setAllCustomFields] = useState<CustomField[]>([]);
  const [predefinedFields, setPredefinedFields] = useState<Record<string, PredefinedField[]>>({});
  const [manuallyShownFieldIds, setManuallyShownFieldIds] = useState<Set<string>>(new Set());
  const [editingFieldId, setEditingFieldId] = useState<string | null>(null);
  const [fieldDraft, setFieldDraft] = useState<string>("");
  const [savingFieldId, setSavingFieldId] = useState<string | null>(null);
  const [showFieldPicker, setShowFieldPicker] = useState(false);

  useEffect(() => {
    apiTags().then(setAllTags).catch(() => {});
    apiCustomFields().then(setAllCustomFields).catch(() => {});
    apiPredefinedFields().then(setPredefinedFields).catch(() => {});
    apiCorrespondents().then(setAllCorrespondents).catch(() => {});
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

  // Lazy-load this document's audit trail only when the History tab is opened.
  useEffect(() => {
    if (activeTab !== "history") return;
    setHistoryLoading(true);
    apiActivity({ documentId: id })
      .then(setHistory)
      .catch(() => {})
      .finally(() => setHistoryLoading(false));
  }, [activeTab, id]);

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

  const openShareModal = () => {
    if (!doc) return;
    setShowShareModal(true);
    setSharesLoading(true);
    apiListShares(doc.id)
      .then(setShares)
      .catch(() => {})
      .finally(() => setSharesLoading(false));
  };

  const handleCreateShare = async () => {
    if (!doc) return;
    setCreatingShare(true);
    try {
      const share = await apiCreateShare(doc.id, newShareDays);
      setShares((prev) => [share, ...prev]);
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Failed to create share link");
    } finally {
      setCreatingShare(false);
    }
  };

  const handleRevokeShare = async (shareId: string) => {
    try {
      await apiRevokeShare(shareId);
      setShares((prev) => prev.filter((s) => s.id !== shareId));
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Failed to revoke share link");
    }
  };

  const handleCopyShareLink = (share: DocumentShare) => {
    const link = `${window.location.origin}/shared/${share.token}`;
    navigator.clipboard.writeText(link);
    setCopiedShareId(share.id);
    setTimeout(() => setCopiedShareId(null), 2000);
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
      correspondentId: doc.correspondent?.id ?? "",
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
        correspondentId: editDraft.correspondentId || null,
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

  const openExtractionEdit = () => {
    if (!doc?.extractedData) return;
    const draft: Record<string, string> = {};
    for (const [k, v] of Object.entries(doc.extractedData)) {
      if (!Array.isArray(v) && v !== null && typeof v !== "object") {
        draft[k] = String(v);
      }
    }
    setExtractionDraft(draft);
    setExtractionEditing(true);
  };

  const handleSaveExtraction = async () => {
    if (!doc) return;
    setSavingExtraction(true);
    setActionError("");
    try {
      const patch: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(extractionDraft)) {
        const original = doc.extractedData?.[k];
        if (typeof original === "number") {
          const n = parseFloat(v);
          patch[k] = isNaN(n) ? v : n;
        } else {
          patch[k] = v;
        }
      }
      const updated = await apiPatchDocument(doc.id, { extractedDataPatch: patch });
      setDoc(updated);
      setExtractionEditing(false);
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSavingExtraction(false);
    }
  };

  const handleSetFieldValue = async (fieldId: string, value: unknown) => {
    if (!doc) return;
    setSavingFieldId(fieldId);
    setActionError("");
    try {
      await apiSetFieldValue(doc.id, fieldId, value);
      const refreshed = await apiDocument(doc.id);
      setDoc(refreshed);
      setEditingFieldId(null);
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : "Failed to save field value");
    } finally {
      setSavingFieldId(null);
    }
  };

  const handleClearFieldValue = async (fieldId: string) => {
    if (!doc) return;
    setActionError("");
    try {
      await apiDeleteFieldValue(doc.id, fieldId);
      const refreshed = await apiDocument(doc.id);
      setDoc(refreshed);
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : "Failed to clear field value");
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
          {doc.duplicateOfDocumentId && (
            <Link
              href={`/documents/${doc.duplicateOfDocumentId}`}
              className="px-2 py-0.5 bg-amber-100 text-amber-700 rounded text-xs font-medium hover:bg-amber-200 transition-colors"
              title="Same vendor and invoice number as another document — click to compare"
            >
              Possible duplicate
            </Link>
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
          {!isTrashed && (
            <button
              onClick={openShareModal}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-slate-200 rounded-lg hover:bg-slate-50 text-slate-600 transition-colors"
            >
              <Share2 className="w-3.5 h-3.5" />
              Share
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

      {/* Share modal */}
      {showShareModal && doc && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold text-slate-800 flex items-center gap-2">
                <Share2 className="w-4 h-4 text-slate-400" />
                Share &quot;{doc.title || doc.originalFilename}&quot;
              </h2>
              <button onClick={() => setShowShareModal(false)} className="text-slate-400 hover:text-slate-600">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex items-center gap-2 mb-4">
              <label className="text-xs text-slate-500">Expires in</label>
              <select
                value={newShareDays}
                onChange={(e) => setNewShareDays(Number(e.target.value))}
                className="text-sm px-2 py-1.5 border border-slate-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {[1, 7, 14, 30].map((d) => (
                  <option key={d} value={d}>{d} day{d > 1 ? "s" : ""}</option>
                ))}
              </select>
              <button
                onClick={handleCreateShare}
                disabled={creatingShare}
                className="ml-auto flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm rounded-lg transition-colors"
              >
                {creatingShare ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
                New link
              </button>
            </div>

            <div className="border-t border-slate-100 pt-3">
              {sharesLoading ? (
                <div className="flex justify-center py-6">
                  <Loader2 className="w-4 h-4 animate-spin text-slate-400" />
                </div>
              ) : shares.length === 0 ? (
                <p className="text-sm text-slate-400 text-center py-6">
                  No active share links. Create one above to send this document to anyone — no account needed.
                </p>
              ) : (
                <div className="space-y-2 max-h-60 overflow-y-auto">
                  {shares.map((share) => {
                    const expired = new Date(share.expiresAt) < new Date();
                    return (
                      <div
                        key={share.id}
                        className="flex items-center gap-2 px-3 py-2 bg-slate-50 rounded-lg text-xs"
                      >
                        <div className="flex-1 min-w-0">
                          <p className={`font-mono truncate ${expired ? "text-slate-300 line-through" : "text-slate-600"}`}>
                            /shared/{share.token.slice(0, 16)}…
                          </p>
                          <p className="text-slate-400">
                            {expired ? "Expired" : `Expires ${new Date(share.expiresAt).toLocaleDateString()}`}
                          </p>
                        </div>
                        {!expired && (
                          <button
                            onClick={() => handleCopyShareLink(share)}
                            className="p-1.5 rounded hover:bg-slate-200 text-slate-500 flex-shrink-0"
                            title="Copy link"
                          >
                            {copiedShareId === share.id ? (
                              <Check className="w-3.5 h-3.5 text-green-600" />
                            ) : (
                              <Copy className="w-3.5 h-3.5" />
                            )}
                          </button>
                        )}
                        <button
                          onClick={() => handleRevokeShare(share.id)}
                          className="p-1.5 rounded hover:bg-red-50 text-slate-400 hover:text-red-500 flex-shrink-0"
                          title="Revoke"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

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
            {(["extracted", "metadata", "raw", "history"] as const).map((tab) => (
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
                  : tab === "raw"
                  ? "Raw JSON"
                  : "History"}
              </button>
            ))}
          </div>

          <div className="flex-1 overflow-y-auto p-4">
            {activeTab === "extracted" && (
              <div className="space-y-4">
                {/* ---- Extracted structured data ---- */}
                {doc.extractedData ? (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      {doc.confidence != null && (
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-slate-400 capitalize">{doc.documentType}</span>
                          <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${doc.confidence >= 0.7 ? "bg-green-100 text-green-700" : "bg-yellow-100 text-yellow-700"}`}>
                            {Math.round(doc.confidence * 100)}% confident
                          </span>
                        </div>
                      )}
                      {!extractionEditing && !isTrashed && (
                        <button
                          onClick={openExtractionEdit}
                          className="flex items-center gap-1 text-xs text-slate-400 hover:text-blue-600 transition-colors ml-auto"
                          title="Correct extracted fields"
                        >
                          <Pencil className="w-3 h-3" /> Correct
                        </button>
                      )}
                    </div>

                    {extractionEditing ? (
                      /* ---- Correction form ---- */
                      <div className="space-y-2">
                        {Object.entries(extractionDraft).map(([key]) => (
                          <div key={key}>
                            <label className="text-xs text-slate-500 capitalize block mb-0.5">
                              {key.replace(/_/g, " ")}
                            </label>
                            <input
                              value={extractionDraft[key]}
                              onChange={(e) =>
                                setExtractionDraft((d) => ({ ...d, [key]: e.target.value }))
                              }
                              className="w-full px-2 py-1.5 border border-slate-200 rounded text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
                            />
                          </div>
                        ))}
                        <div className="flex gap-2 pt-1">
                          <button
                            onClick={handleSaveExtraction}
                            disabled={savingExtraction}
                            className="flex items-center gap-1 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-xs rounded-lg"
                          >
                            {savingExtraction ? (
                              <Loader2 className="w-3 h-3 animate-spin" />
                            ) : (
                              <Save className="w-3 h-3" />
                            )}
                            Save corrections
                          </button>
                          <button
                            onClick={() => setExtractionEditing(false)}
                            disabled={savingExtraction}
                            className="flex items-center gap-1 px-3 py-1.5 border border-slate-200 hover:bg-slate-50 text-slate-600 text-xs rounded-lg"
                          >
                            <X className="w-3 h-3" /> Cancel
                          </button>
                        </div>
                      </div>
                    ) : (
                      /* ---- Read-only view ---- */
                      <>
                        {Object.entries(doc.extractedData).map(([key, value]) => {
                          if (Array.isArray(value)) {
                            return (
                              <div key={key} className="bg-slate-50 rounded-lg p-3">
                                <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                                  {key.replace(/([A-Z])/g, " $1").replace(/_/g, " ").trim()}
                                </p>
                                <div className="space-y-2">
                                  {(value as Record<string, unknown>[]).map((item, i) => (
                                    <div key={i} className="bg-white border border-slate-200 rounded p-2 text-xs space-y-1">
                                      {Object.entries(item).map(([k, v]) => (
                                        <div key={k} className="flex items-center justify-between gap-2">
                                          <span className="text-slate-400 capitalize">{k.replace(/([A-Z])/g, " $1")}</span>
                                          <span className="font-medium text-slate-700 text-right">{String(v)}</span>
                                        </div>
                                      ))}
                                    </div>
                                  ))}
                                </div>
                              </div>
                            );
                          }
                          return (
                            <div key={key} className="flex items-start justify-between gap-3 py-2 border-b border-slate-50">
                              <span className="text-xs text-slate-500 capitalize flex-shrink-0">
                                {key.replace(/_/g, " ")}
                              </span>
                              <span className="text-xs font-semibold text-slate-800 text-right">
                                {typeof value === "number" && key.toLowerCase().includes("amount")
                                  ? `MYR ${(value as number).toFixed(2)}`
                                  : String(value)}
                              </span>
                            </div>
                          );
                        })}
                      </>
                    )}
                  </div>
                ) : doc.extractedText ? (
                  <div className="space-y-2">
                    <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
                      Extracted Text
                    </p>
                    <pre className="text-xs text-slate-700 whitespace-pre-wrap leading-relaxed bg-slate-50 rounded-lg p-3 max-h-[20rem] overflow-y-auto">
                      {doc.extractedText}
                    </pre>
                    <div className="flex items-center justify-between">
                      <p className="text-xs text-slate-400">Structured extraction has not run yet.</p>
                      <button onClick={handleExtract} className="text-xs text-blue-600 hover:underline flex items-center gap-1">
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
                        <button onClick={handleRetry} className="mt-2 text-xs text-blue-600 hover:underline flex items-center gap-1">
                          <RefreshCw className="w-3 h-3" /> Retry processing
                        </button>
                      </>
                    )}
                  </div>
                )}

                {/* ---- Custom fields section ---- */}
                {/* Scoped to fields predefined for this doc's type, plus any
                    field that already has a value (so ad-hoc/legacy values
                    never silently disappear) or was just manually added below. */}
                {allCustomFields.length > 0 && (() => {
                  const predefinedIds = new Set(
                    (predefinedFields[doc.documentType] ?? []).map((p) => p.fieldId)
                  );
                  const valueIds = new Set((doc.customFieldValues ?? []).map((v) => v.fieldId));
                  const visibleFields = allCustomFields.filter(
                    (f) => predefinedIds.has(f.id) || valueIds.has(f.id) || manuallyShownFieldIds.has(f.id)
                  );
                  const addableFields = allCustomFields.filter(
                    (f) => !predefinedIds.has(f.id) && !valueIds.has(f.id) && !manuallyShownFieldIds.has(f.id)
                  );

                  return (
                    <div className="pt-3 border-t border-slate-100">
                      <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                        Custom Fields
                      </p>
                      <div className="space-y-2">
                        {visibleFields.map((field) => {
                          const existing = doc.customFieldValues?.find(
                            (v: FieldValue) => v.fieldId === field.id
                          );
                          const isEditing = editingFieldId === field.id;

                          return (
                            <div key={field.id} className="flex items-center gap-2 py-1.5 border-b border-slate-50">
                              <span className="text-xs text-slate-500 flex-shrink-0 w-28 truncate">{field.name}</span>
                              {isEditing ? (
                                <>
                                  <CustomFieldInput
                                    fieldType={field.fieldType}
                                    options={field.options}
                                    value={fieldDraft}
                                    onChange={setFieldDraft}
                                  />
                                  <button
                                    onClick={() =>
                                      handleSetFieldValue(
                                        field.id,
                                        parseCustomFieldValue(field.fieldType, fieldDraft)
                                      )
                                    }
                                    disabled={savingFieldId === field.id}
                                    className="p-1 text-blue-600 hover:text-blue-800 disabled:opacity-50"
                                  >
                                    {savingFieldId === field.id ? (
                                      <Loader2 className="w-3 h-3 animate-spin" />
                                    ) : (
                                      <Save className="w-3 h-3" />
                                    )}
                                  </button>
                                  <button
                                    onClick={() => setEditingFieldId(null)}
                                    className="p-1 text-slate-400 hover:text-slate-600"
                                  >
                                    <X className="w-3 h-3" />
                                  </button>
                                </>
                              ) : (
                                <>
                                  <span className="flex-1 text-xs text-slate-700 font-medium">
                                    {existing != null
                                      ? field.fieldType === "boolean"
                                        ? existing.value ? "Yes" : "No"
                                        : String(existing.value)
                                      : <span className="text-slate-300">—</span>}
                                  </span>
                                  {!isTrashed && (
                                    <>
                                      <button
                                        onClick={() => {
                                          setEditingFieldId(field.id);
                                          setFieldDraft(
                                            existing != null ? String(existing.value) : ""
                                          );
                                        }}
                                        className="p-1 text-slate-300 hover:text-blue-500"
                                        title="Edit"
                                      >
                                        <Pencil className="w-3 h-3" />
                                      </button>
                                      {existing != null && (
                                        <button
                                          onClick={() => handleClearFieldValue(field.id)}
                                          className="p-1 text-slate-300 hover:text-red-500"
                                          title="Clear"
                                        >
                                          <X className="w-3 h-3" />
                                        </button>
                                      )}
                                    </>
                                  )}
                                </>
                              )}
                            </div>
                          );
                        })}
                      </div>

                      {!isTrashed && addableFields.length > 0 && (
                        <div className="relative mt-2">
                          <button
                            onClick={() => setShowFieldPicker((v) => !v)}
                            className="px-2.5 py-1 border border-dashed border-slate-300 text-slate-400 rounded text-xs hover:border-blue-400 hover:text-blue-600 transition-colors inline-flex items-center gap-1.5"
                          >
                            <Plus className="w-3.5 h-3.5" /> Add field
                          </button>
                          {showFieldPicker && (
                            <div className="absolute top-full mt-1 left-0 bg-white border border-slate-200 rounded-lg shadow-lg py-1 z-10 min-w-36 max-h-44 overflow-y-auto">
                              {addableFields.map((f) => (
                                <button
                                  key={f.id}
                                  onClick={() => {
                                    setManuallyShownFieldIds((prev) => new Set(prev).add(f.id));
                                    setEditingFieldId(f.id);
                                    setFieldDraft("");
                                    setShowFieldPicker(false);
                                  }}
                                  className="w-full px-3 py-2 hover:bg-slate-50 text-xs text-left"
                                >
                                  {f.name}
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })()}
              </div>
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
                    <div>
                      <label className="text-xs text-slate-500 block mb-1">Correspondent</label>
                      <select
                        value={editDraft.correspondentId}
                        onChange={(e) =>
                          setEditDraft((d) => ({ ...d, correspondentId: e.target.value }))
                        }
                        className="w-full px-2 py-1.5 rounded border border-slate-200 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                      >
                        <option value="">— None —</option>
                        {allCorrespondents.map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.name}
                          </option>
                        ))}
                      </select>
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

            {activeTab === "history" && (
              <div className="space-y-3">
                {!history || history.items.length === 0 ? (
                  <div className="bg-slate-50 rounded-lg p-4 text-center">
                    <p className="text-slate-400 text-xs">
                      {historyLoading ? "Loading…" : "No activity recorded for this document."}
                    </p>
                  </div>
                ) : (
                  history.items.map((event) => (
                    <div key={event.id} className="flex items-start gap-2.5">
                      <div className="mt-0.5">
                        <ActivityIcon type={event.type} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-xs text-slate-700">
                          <span className="font-medium text-slate-800">{event.userName}</span>{" "}
                          <ActivityLabel event={event} />
                        </p>
                        <p className="text-[11px] text-slate-400 mt-0.5">
                          {formatRelativeTime(event.timestamp)}
                        </p>
                      </div>
                    </div>
                  ))
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
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-sm font-medium"
                  style={{ background: tag.color + "22", color: tag.color }}
                >
                  {tag.name}
                  <button
                    onClick={() => handleUnassignTag(tag.id)}
                    className="opacity-60 hover:opacity-100"
                    title="Remove tag"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))}
              <div className="relative">
                <button
                  onClick={() => setShowTagPicker((v) => !v)}
                  className="px-2.5 py-1 border border-dashed border-slate-300 text-slate-400 rounded text-sm hover:border-blue-400 hover:text-blue-600 transition-colors inline-flex items-center gap-1.5"
                >
                  <Plus className="w-3.5 h-3.5" /> Add
                </button>
                {showTagPicker && allTags.length > 0 && (
                  <div className="absolute bottom-full mb-1 left-0 bg-white border border-slate-200 rounded-lg shadow-lg py-1 z-10 min-w-36 max-h-44 overflow-y-auto">
                    {allTags
                      .filter((t) => !doc.tags.some((dt) => dt.id === t.id))
                      .map((t) => (
                        <button
                          key={t.id}
                          onClick={() => handleAssignTag(t.id)}
                          className="w-full flex items-center gap-2 px-3 py-2 hover:bg-slate-50 text-sm text-left"
                        >
                          <span
                            className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                            style={{ background: t.color }}
                          />
                          {t.name}
                        </button>
                      ))}
                    {allTags.filter((t) => !doc.tags.some((dt) => dt.id === t.id)).length === 0 && (
                      <p className="px-3 py-2 text-sm text-slate-400">All tags assigned</p>
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
