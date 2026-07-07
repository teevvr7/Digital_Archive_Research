"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  FileText,
  FileImage,
  FileScan,
  FileSpreadsheet,
  Presentation,
  Mail,
  Search,
  Upload,
  Download,
  Eye,
  RefreshCw,
  ChevronDown,
  Loader2,
  Trash2,
  RotateCcw,
  Tag as TagIcon,
  LayoutGrid,
  List,
  Bookmark,
  BookmarkPlus,
  Users,
  X,
  CheckSquare,
} from "lucide-react";
import { StatusBadge } from "@/components/status-badge";
import { formatBytes, formatRelativeTime } from "@/lib/format";
import {
  apiDocuments,
  apiDownloadUrl,
  apiExtractMissing,
  apiRetryDocument,
  apiTrashDocument,
  apiRestoreDocument,
  apiEmptyTrash,
  apiTags,
  apiCorrespondents,
  apiThumbnailUrl,
  apiSavedViews,
  apiCreateSavedView,
  apiBulkTrash,
  apiBulkTag,
  apiBulkSetType,
  type DocumentListResponse,
} from "@/lib/api";
import type { Correspondent, Document, DocumentType, ProcessingStatus, SavedView, Tag } from "@/types";

const TERMINAL_STATUSES = new Set<ProcessingStatus>(["completed", "needs_review", "failed"]);
const POLL_INTERVAL_MS = 3000;

const ALL_STATUSES: ProcessingStatus[] = [
  "queued",
  "extracting_text",
  "ocr_processing",
  "ai_extraction",
  "completed",
  "needs_review",
  "failed",
];
const ALL_TYPES: DocumentType[] = [
  "invoice",
  "receipt",
  "contract",
  "report",
  "letter",
  "form",
  "other",
];

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function DocIcon({ doc }: { doc: Document }) {
  if (doc.mimeType.startsWith("image/"))
    return <FileImage className="w-4 h-4 text-slate-400" />;
  if (doc.mimeType === "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return <FileSpreadsheet className="w-4 h-4 text-slate-400" />;
  if (doc.mimeType === "application/vnd.openxmlformats-officedocument.presentationml.presentation")
    return <Presentation className="w-4 h-4 text-slate-400" />;
  if (doc.mimeType === "message/rfc822") return <Mail className="w-4 h-4 text-slate-400" />;
  if (doc.mimeType === "application/pdf" && !doc.hasTextLayer)
    return <FileScan className="w-4 h-4 text-slate-400" />;
  return <FileText className="w-4 h-4 text-slate-400" />;
}

function ThumbnailImage({ docId }: { docId: string }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    apiThumbnailUrl(docId).then((r) => { if (!cancelled) setUrl(r.url); }).catch(() => {});
    return () => { cancelled = true; };
  }, [docId]);
  if (!url) return null;
  return <img src={url} alt="" className="w-full h-full object-cover" />;
}

function DocCard({
  doc,
  selected,
  onSelect,
}: {
  doc: Document;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <div
      className={`bg-white border rounded-xl overflow-hidden transition-all ${
        selected ? "border-blue-400 ring-2 ring-blue-200" : "border-slate-200 hover:border-slate-300"
      }`}
    >
      {/* Thumbnail */}
      <div className="relative aspect-[4/3] bg-slate-100">
        <div className="absolute inset-0 flex items-center justify-center">
          {doc.hasThumbnail ? (
            <ThumbnailImage docId={doc.id} />
          ) : (
            <div className="text-slate-300">
              <DocIcon doc={doc} />
            </div>
          )}
        </div>
        <input
          type="checkbox"
          checked={selected}
          onChange={onSelect}
          className="absolute top-2 left-2 w-4 h-4 rounded border-slate-300 accent-blue-600 cursor-pointer"
          onClick={(e) => e.stopPropagation()}
        />
        <div className="absolute top-2 right-2">
          <StatusBadge status={doc.status} />
        </div>
      </div>

      {/* Info */}
      <div className="p-3 border-t border-slate-100">
        <Link
          href={`/documents/${doc.id}`}
          className="block text-sm font-medium text-slate-800 hover:text-blue-700 truncate"
          title={doc.title || doc.originalFilename}
        >
          {doc.title || doc.originalFilename}
        </Link>
        <p className="text-xs text-slate-400 mt-0.5">{formatRelativeTime(doc.uploadedAt)}</p>
        {doc.tags.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-1.5">
            {doc.tags.slice(0, 3).map((tag) => (
              <span
                key={tag.id}
                className="px-1.5 py-0.5 rounded text-xs font-medium"
                style={{ background: tag.color + "22", color: tag.color }}
              >
                {tag.name}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function DocumentsPage() {
  // ---- Filters ----
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<ProcessingStatus | "all">("all");
  const [typeFilter, setTypeFilter] = useState<DocumentType | "all">("all");
  const [tagFilter, setTagFilter] = useState<string>("all");
  const [correspondentFilter, setCorrespondentFilter] = useState<string>("all");
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");
  const [inbox, setInbox] = useState(false);
  const [sortBy, setSortBy] = useState("date_desc");
  const [page, setPage] = useState(1);
  const [trashed, setTrashed] = useState(false);

  // ---- View ----
  const [viewMode, setViewMode] = useState<"table" | "grid">("table");

  // ---- Data ----
  const [data, setData] = useState<DocumentListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [allTags, setAllTags] = useState<Tag[]>([]);
  const [allCorrespondents, setAllCorrespondents] = useState<Correspondent[]>([]);
  const [savedViews, setSavedViews] = useState<SavedView[]>([]);

  // ---- Bulk selection ----
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkLoading, setBulkLoading] = useState(false);
  const [showBulkTagMenu, setShowBulkTagMenu] = useState(false);
  const [showBulkTypeMenu, setShowBulkTypeMenu] = useState(false);

  // ---- Save view form ----
  const [showSaveView, setShowSaveView] = useState(false);
  const [saveViewName, setSaveViewName] = useState("");
  const [savingView, setSavingView] = useState(false);

  // ---- Misc ----
  const [emptyingTrash, setEmptyingTrash] = useState(false);
  const [extractingMissing, setExtractingMissing] = useState(false);

  const bulkTagRef = useRef<HTMLDivElement>(null);
  const bulkTypeRef = useRef<HTMLDivElement>(null);

  // Load static lists once
  useEffect(() => {
    apiTags().then(setAllTags).catch(() => {});
    apiCorrespondents().then(setAllCorrespondents).catch(() => {});
    apiSavedViews().then(setSavedViews).catch(() => {});
  }, []);

  // Close bulk menus on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (bulkTagRef.current && !bulkTagRef.current.contains(e.target as Node))
        setShowBulkTagMenu(false);
      if (bulkTypeRef.current && !bulkTypeRef.current.contains(e.target as Node))
        setShowBulkTypeMenu(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const buildQuery = () => ({
    status: statusFilter === "all" ? undefined : statusFilter,
    type: typeFilter === "all" ? undefined : typeFilter,
    tag_id: tagFilter !== "all" ? tagFilter : undefined,
    correspondent_id: correspondentFilter !== "all" ? correspondentFilter : undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    inbox: inbox || undefined,
    q: query || undefined,
    sort: sortBy,
    page,
    trashed: trashed || undefined,
  });

  const refreshDocuments = () => {
    setLoading(true);
    setError("");
    apiDocuments(buildQuery())
      .then((d) => { setData(d); setSelectedIds(new Set()); })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    refreshDocuments();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, typeFilter, tagFilter, correspondentFilter, dateFrom, dateTo, inbox, sortBy, page, query, trashed]);

  // Silent poll while any doc is still processing
  useEffect(() => {
    const hasInProgress = data?.items.some((d) => !TERMINAL_STATUSES.has(d.status));
    if (!hasInProgress) return;
    const timerId = setInterval(() => {
      apiDocuments(buildQuery()).then(setData).catch(() => {});
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timerId);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, statusFilter, typeFilter, tagFilter, correspondentFilter, dateFrom, dateTo, inbox, sortBy, page, query, trashed]);

  const docs = data?.items ?? [];
  const total = data?.total ?? 0;
  const pageSize = data?.pageSize ?? 20;
  const totalPages = Math.ceil(total / pageSize);

  // ---- Filter helpers ----
  const resetFilters = () => {
    setQuery("");
    setStatusFilter("all");
    setTypeFilter("all");
    setTagFilter("all");
    setCorrespondentFilter("all");
    setDateFrom("");
    setDateTo("");
    setInbox(false);
    setSortBy("date_desc");
    setPage(1);
  };

  const hasActiveFilters =
    query || statusFilter !== "all" || typeFilter !== "all" || tagFilter !== "all" ||
    correspondentFilter !== "all" || dateFrom || dateTo || inbox;

  // ---- Apply saved view ----
  const applyView = (view: SavedView) => {
    const s = view.filterState as Record<string, unknown>;
    setQuery((s.q as string) || "");
    setStatusFilter((s.status as ProcessingStatus | "all") || "all");
    setTypeFilter((s.type as DocumentType | "all") || "all");
    setTagFilter((s.tag_id as string) || "all");
    setCorrespondentFilter((s.correspondent_id as string) || "all");
    setDateFrom((s.date_from as string) || "");
    setDateTo((s.date_to as string) || "");
    setInbox(Boolean(s.inbox));
    setSortBy((s.sort as string) || "date_desc");
    setPage(1);
  };

  const currentFilterState = () => ({
    ...(query && { q: query }),
    ...(statusFilter !== "all" && { status: statusFilter }),
    ...(typeFilter !== "all" && { type: typeFilter }),
    ...(tagFilter !== "all" && { tag_id: tagFilter }),
    ...(correspondentFilter !== "all" && { correspondent_id: correspondentFilter }),
    ...(dateFrom && { date_from: dateFrom }),
    ...(dateTo && { date_to: dateTo }),
    ...(inbox && { inbox: true }),
    ...(sortBy !== "date_desc" && { sort: sortBy }),
  });

  const handleSaveView = async () => {
    if (!saveViewName.trim()) return;
    setSavingView(true);
    try {
      const created = await apiCreateSavedView({
        name: saveViewName.trim(),
        filterState: currentFilterState(),
      });
      setSavedViews((prev) => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)));
      setShowSaveView(false);
      setSaveViewName("");
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Failed to save view");
    } finally {
      setSavingView(false);
    }
  };

  // ---- Selection helpers ----
  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === docs.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(docs.map((d) => d.id)));
    }
  };

  // ---- Bulk actions ----
  const handleBulkTrash = async () => {
    if (!confirm(`Move ${selectedIds.size} document${selectedIds.size !== 1 ? "s" : ""} to trash?`)) return;
    setBulkLoading(true);
    try {
      await apiBulkTrash([...selectedIds]);
      setSelectedIds(new Set());
      refreshDocuments();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Bulk trash failed");
    } finally {
      setBulkLoading(false);
    }
  };

  const handleBulkTag = async (tagId: string, action: "assign" | "remove") => {
    setBulkLoading(true);
    setShowBulkTagMenu(false);
    try {
      await apiBulkTag([...selectedIds], tagId, action);
      refreshDocuments();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Bulk tag failed");
    } finally {
      setBulkLoading(false);
    }
  };

  const handleBulkSetType = async (docType: string) => {
    setBulkLoading(true);
    setShowBulkTypeMenu(false);
    try {
      await apiBulkSetType([...selectedIds], docType);
      refreshDocuments();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Bulk set type failed");
    } finally {
      setBulkLoading(false);
    }
  };

  // ---- Single-doc actions ----
  const handleDownload = async (doc: Document) => {
    try {
      const { url } = await apiDownloadUrl(doc.id);
      window.open(url, "_blank");
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Download failed");
    }
  };

  const handleRetry = async (doc: Document) => {
    try {
      await apiRetryDocument(doc.id);
      setPage((p) => p);
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Retry failed");
    }
  };

  const handleTrash = async (doc: Document) => {
    try {
      await apiTrashDocument(doc.id);
      setData((d) => d ? { ...d, items: d.items.filter((i) => i.id !== doc.id), total: d.total - 1 } : d);
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Move to trash failed");
    }
  };

  const handleRestore = async (doc: Document) => {
    try {
      await apiRestoreDocument(doc.id);
      setData((d) => d ? { ...d, items: d.items.filter((i) => i.id !== doc.id), total: d.total - 1 } : d);
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Restore failed");
    }
  };

  const handleEmptyTrash = async () => {
    if (!confirm("Permanently delete all trashed documents? This cannot be undone.")) return;
    setEmptyingTrash(true);
    try {
      const { deleted } = await apiEmptyTrash();
      alert(`Permanently deleted ${deleted} document${deleted !== 1 ? "s" : ""}.`);
      setData(null);
      setPage(1);
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Failed to empty trash");
    } finally {
      setEmptyingTrash(false);
    }
  };

  const handleExtractMissing = async () => {
    setExtractingMissing(true);
    try {
      const { enqueued } = await apiExtractMissing();
      alert(`Queued AI extraction for ${enqueued} document${enqueued !== 1 ? "s" : ""}.`);
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Failed to queue extraction");
    } finally {
      setExtractingMissing(false);
    }
  };

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">
            {trashed ? "Trash" : inbox ? "Inbox" : "Documents"}
          </h1>
          <p className="text-slate-500 text-sm mt-0.5">
            {total} document{total !== 1 ? "s" : ""}
            {trashed && " in trash"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* View toggle */}
          <div className="flex border border-slate-200 rounded-lg overflow-hidden">
            <button
              onClick={() => setViewMode("table")}
              className={`p-2 ${viewMode === "table" ? "bg-slate-100 text-slate-800" : "hover:bg-slate-50 text-slate-400"}`}
              title="Table view"
            >
              <List className="w-4 h-4" />
            </button>
            <button
              onClick={() => setViewMode("grid")}
              className={`p-2 ${viewMode === "grid" ? "bg-slate-100 text-slate-800" : "hover:bg-slate-50 text-slate-400"}`}
              title="Grid view"
            >
              <LayoutGrid className="w-4 h-4" />
            </button>
          </div>

          <button
            onClick={() => { setTrashed((v) => !v); setPage(1); }}
            className={`inline-flex items-center gap-2 border px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
              trashed
                ? "border-red-300 bg-red-50 text-red-700 hover:bg-red-100"
                : "border-slate-300 hover:bg-slate-50 text-slate-700"
            }`}
          >
            <Trash2 className="w-4 h-4" />
            {trashed ? "Exit Trash" : "Trash"}
          </button>
          {trashed && (
            <button
              onClick={handleEmptyTrash}
              disabled={emptyingTrash || total === 0}
              className="inline-flex items-center gap-2 border border-red-300 hover:bg-red-50 text-red-700 px-3 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
            >
              {emptyingTrash ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
              Empty trash
            </button>
          )}
          {!trashed && (
            <>
              <button
                onClick={handleExtractMissing}
                disabled={extractingMissing}
                className="inline-flex items-center gap-2 border border-slate-300 hover:bg-slate-50 text-slate-700 px-3 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
                title="Queue AI extraction for all completed documents without structured data"
              >
                {extractingMissing ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileScan className="w-4 h-4" />}
                Extract structured data
              </button>
              <Link
                href="/upload"
                className="inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-3 py-2 rounded-lg text-sm font-medium transition-colors"
              >
                <Upload className="w-4 h-4" />
                Upload
              </Link>
            </>
          )}
        </div>
      </div>

      {/* Bulk action bar */}
      {selectedIds.size > 0 && (
        <div className="mb-4 flex items-center gap-2 bg-blue-50 border border-blue-200 rounded-xl px-4 py-3">
          <CheckSquare className="w-4 h-4 text-blue-600 flex-shrink-0" />
          <span className="text-sm font-medium text-blue-800">
            {selectedIds.size} selected
          </span>
          <div className="flex items-center gap-2 ml-2">
            {/* Tag menu */}
            {allTags.length > 0 && (
              <div className="relative" ref={bulkTagRef}>
                <button
                  onClick={() => setShowBulkTagMenu((v) => !v)}
                  disabled={bulkLoading}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 text-sm rounded-lg disabled:opacity-50"
                >
                  <TagIcon className="w-3.5 h-3.5" />
                  Tag
                  <ChevronDown className="w-3 h-3" />
                </button>
                {showBulkTagMenu && (
                  <div className="absolute top-full left-0 mt-1 z-20 bg-white border border-slate-200 rounded-xl shadow-lg min-w-44 py-1">
                    <p className="px-3 py-1 text-xs text-slate-400 font-medium uppercase tracking-wide">Assign</p>
                    {allTags.map((tag) => (
                      <button
                        key={`assign-${tag.id}`}
                        onClick={() => handleBulkTag(tag.id, "assign")}
                        className="w-full text-left px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 flex items-center gap-2"
                      >
                        <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: tag.color }} />
                        {tag.name}
                      </button>
                    ))}
                    <div className="border-t border-slate-100 mt-1 pt-1">
                      <p className="px-3 py-1 text-xs text-slate-400 font-medium uppercase tracking-wide">Remove</p>
                      {allTags.map((tag) => (
                        <button
                          key={`remove-${tag.id}`}
                          onClick={() => handleBulkTag(tag.id, "remove")}
                          className="w-full text-left px-3 py-1.5 text-sm text-slate-500 hover:bg-slate-50 flex items-center gap-2"
                        >
                          <span className="w-2.5 h-2.5 rounded-full flex-shrink-0 opacity-50" style={{ background: tag.color }} />
                          {tag.name}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Set type menu */}
            <div className="relative" ref={bulkTypeRef}>
              <button
                onClick={() => setShowBulkTypeMenu((v) => !v)}
                disabled={bulkLoading}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 text-sm rounded-lg disabled:opacity-50"
              >
                Set type
                <ChevronDown className="w-3 h-3" />
              </button>
              {showBulkTypeMenu && (
                <div className="absolute top-full left-0 mt-1 z-20 bg-white border border-slate-200 rounded-xl shadow-lg min-w-36 py-1">
                  {ALL_TYPES.map((t) => (
                    <button
                      key={t}
                      onClick={() => handleBulkSetType(t)}
                      className="w-full text-left px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 capitalize"
                    >
                      {t}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {!trashed && (
              <button
                onClick={handleBulkTrash}
                disabled={bulkLoading}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-white border border-red-200 hover:bg-red-50 text-red-600 text-sm rounded-lg disabled:opacity-50"
              >
                {bulkLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
                Trash
              </button>
            )}
          </div>
          <button
            onClick={() => setSelectedIds(new Set())}
            className="ml-auto text-slate-400 hover:text-slate-600"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Saved views bar */}
      {savedViews.length > 0 && (
        <div className="mb-3 flex items-center gap-2 flex-wrap">
          <Bookmark className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
          {savedViews.map((view) => (
            <button
              key={view.id}
              onClick={() => applyView(view)}
              className="px-2.5 py-1 bg-white border border-slate-200 hover:border-blue-400 hover:bg-blue-50 text-slate-600 hover:text-blue-700 text-xs rounded-lg transition-colors"
            >
              {view.name}
            </button>
          ))}
        </div>
      )}

      {/* Filters */}
      <div className="bg-white border border-slate-200 rounded-xl p-4 mb-4 space-y-3">
        {/* Row 1 */}
        <div className="flex flex-wrap gap-3 items-center">
          <div className="relative flex-1 min-w-52">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              value={query}
              onChange={(e) => { setQuery(e.target.value); setPage(1); }}
              placeholder="Search filename or content…"
              className="w-full pl-9 pr-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-900 placeholder:text-slate-400"
            />
          </div>

          <div className="relative">
            <select
              value={statusFilter}
              onChange={(e) => { setStatusFilter(e.target.value as ProcessingStatus | "all"); setPage(1); }}
              className="appearance-none pl-3 pr-8 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-700 bg-white cursor-pointer"
            >
              <option value="all">All Statuses</option>
              {ALL_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase())}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
          </div>

          <div className="relative">
            <select
              value={typeFilter}
              onChange={(e) => { setTypeFilter(e.target.value as DocumentType | "all"); setPage(1); }}
              className="appearance-none pl-3 pr-8 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-700 bg-white cursor-pointer"
            >
              <option value="all">All Types</option>
              {ALL_TYPES.map((t) => (
                <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
              ))}
            </select>
            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
          </div>

          <div className="relative">
            <select
              value={sortBy}
              onChange={(e) => { setSortBy(e.target.value); setPage(1); }}
              className="appearance-none pl-3 pr-8 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-700 bg-white cursor-pointer"
            >
              <option value="date_desc">Newest first</option>
              <option value="date_asc">Oldest first</option>
              <option value="name_asc">Name A–Z</option>
              <option value="name_desc">Name Z–A</option>
              <option value="size_desc">Largest first</option>
              <option value="size_asc">Smallest first</option>
            </select>
            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
          </div>
        </div>

        {/* Row 2: tags, correspondent, dates, inbox */}
        <div className="flex flex-wrap gap-3 items-center">
          {allTags.length > 0 && (
            <div className="relative">
              <TagIcon className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
              <select
                value={tagFilter}
                onChange={(e) => { setTagFilter(e.target.value); setPage(1); }}
                className="appearance-none pl-8 pr-8 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-700 bg-white cursor-pointer"
              >
                <option value="all">All Tags</option>
                {allTags.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
              <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
            </div>
          )}

          {allCorrespondents.length > 0 && (
            <div className="relative">
              <Users className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
              <select
                value={correspondentFilter}
                onChange={(e) => { setCorrespondentFilter(e.target.value); setPage(1); }}
                className="appearance-none pl-8 pr-8 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-700 bg-white cursor-pointer"
              >
                <option value="all">All Correspondents</option>
                {allCorrespondents.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
            </div>
          )}

          <input
            type="date"
            value={dateFrom}
            onChange={(e) => { setDateFrom(e.target.value); setPage(1); }}
            className="px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-700"
            title="Document date from"
          />
          <span className="text-slate-400 text-sm">→</span>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => { setDateTo(e.target.value); setPage(1); }}
            className="px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-700"
            title="Document date to"
          />

          <button
            onClick={() => { setInbox((v) => !v); setPage(1); }}
            className={`inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border text-sm font-medium transition-colors ${
              inbox
                ? "border-blue-400 bg-blue-50 text-blue-700"
                : "border-slate-200 hover:bg-slate-50 text-slate-600"
            }`}
          >
            <Mail className="w-3.5 h-3.5" />
            Inbox
          </button>

          {/* Save / clear */}
          <div className="flex items-center gap-2 ml-auto">
            {hasActiveFilters && (
              <button
                onClick={resetFilters}
                className="flex items-center gap-1.5 px-3 py-2 text-sm text-slate-500 hover:text-slate-700 border border-slate-200 rounded-lg hover:bg-slate-50"
              >
                <X className="w-3.5 h-3.5" /> Clear
              </button>
            )}
            {!showSaveView ? (
              <button
                onClick={() => setShowSaveView(true)}
                className="flex items-center gap-1.5 px-3 py-2 text-sm text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50"
                title="Save current filters as a view"
              >
                <BookmarkPlus className="w-3.5 h-3.5" />
                Save view
              </button>
            ) : (
              <div className="flex items-center gap-1.5">
                <input
                  autoFocus
                  value={saveViewName}
                  onChange={(e) => setSaveViewName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleSaveView();
                    if (e.key === "Escape") { setShowSaveView(false); setSaveViewName(""); }
                  }}
                  placeholder="View name…"
                  className="px-2.5 py-1.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 w-36"
                />
                <button
                  onClick={handleSaveView}
                  disabled={savingView || !saveViewName.trim()}
                  className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm rounded-lg"
                >
                  {savingView ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : "Save"}
                </button>
                <button
                  onClick={() => { setShowSaveView(false); setSaveViewName(""); }}
                  className="p-1.5 text-slate-400 hover:text-slate-600"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {error && (
        <div className="mb-4 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
          {error}
        </div>
      )}

      {/* Content */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
        </div>
      ) : viewMode === "grid" ? (
        <>
          {docs.length === 0 ? (
            <div className="text-center py-16 text-slate-400 text-sm">
              No documents match your filters.
            </div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
              {docs.map((doc) => (
                <DocCard
                  key={doc.id}
                  doc={doc}
                  selected={selectedIds.has(doc.id)}
                  onSelect={() => toggleSelect(doc.id)}
                />
              ))}
            </div>
          )}
        </>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50">
                <th className="px-4 py-3 w-8">
                  <input
                    type="checkbox"
                    checked={docs.length > 0 && selectedIds.size === docs.length}
                    onChange={toggleSelectAll}
                    className="rounded border-slate-300 accent-blue-600 cursor-pointer"
                  />
                </th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Document</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Type</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Status</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Date</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Size</th>
                <th className="text-right px-6 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {docs.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-6 py-12 text-center text-slate-400 text-sm">
                    No documents match your filters.
                  </td>
                </tr>
              ) : (
                docs.map((doc) => (
                  <tr key={doc.id} className={`hover:bg-slate-50 transition-colors group ${selectedIds.has(doc.id) ? "bg-blue-50" : ""}`}>
                    <td className="px-4 py-3.5">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(doc.id)}
                        onChange={() => toggleSelect(doc.id)}
                        className="rounded border-slate-300 accent-blue-600 cursor-pointer"
                      />
                    </td>
                    <td className="px-4 py-3.5">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 bg-slate-100 rounded-lg flex items-center justify-center flex-shrink-0">
                          <DocIcon doc={doc} />
                        </div>
                        <div className="min-w-0">
                          <Link
                            href={`/documents/${doc.id}`}
                            className="font-medium text-slate-800 group-hover:text-blue-700 truncate block max-w-xs"
                            title={doc.title || doc.originalFilename}
                          >
                            {doc.title || doc.originalFilename}
                          </Link>
                          <div className="flex items-center gap-1.5 mt-0.5">
                            {doc.correspondent && (
                              <span className="text-xs text-slate-400">{doc.correspondent.name}</span>
                            )}
                            {doc.tags.slice(0, 3).map((tag) => (
                              <span
                                key={tag.id}
                                className="px-1.5 py-0.5 rounded text-xs font-medium"
                                style={{ background: tag.color + "22", color: tag.color }}
                              >
                                {tag.name}
                              </span>
                            ))}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3.5">
                      <span className="px-2 py-0.5 bg-slate-100 text-slate-600 rounded text-xs capitalize">
                        {doc.documentType}
                      </span>
                    </td>
                    <td className="px-4 py-3.5">
                      <StatusBadge status={doc.status} />
                    </td>
                    <td className="px-4 py-3.5 text-slate-500 text-xs">
                      <div>{doc.uploadedBy}</div>
                      <div className="text-slate-400">{formatRelativeTime(doc.uploadedAt)}</div>
                      <div className="text-slate-400">{doc.documentDate || doc.uploadedAt.split("T")[0]}</div>
                    </td>
                    <td className="px-4 py-3.5 text-slate-500 text-xs">
                      {formatBytes(doc.sizeBytes)}
                    </td>
                    <td className="px-6 py-3.5">
                      <div className="flex items-center justify-end gap-1">
                        <Link
                          href={`/documents/${doc.id}`}
                          className="p-1.5 rounded-md hover:bg-slate-100 text-slate-400 hover:text-slate-700 transition-colors"
                          title="View"
                        >
                          <Eye className="w-3.5 h-3.5" />
                        </Link>
                        {trashed ? (
                          <button
                            onClick={() => handleRestore(doc)}
                            className="p-1.5 rounded-md hover:bg-slate-100 text-slate-400 hover:text-green-600 transition-colors"
                            title="Restore"
                          >
                            <RotateCcw className="w-3.5 h-3.5" />
                          </button>
                        ) : (
                          <>
                            <button
                              onClick={() => handleDownload(doc)}
                              className="p-1.5 rounded-md hover:bg-slate-100 text-slate-400 hover:text-slate-700 transition-colors"
                              title="Download"
                            >
                              <Download className="w-3.5 h-3.5" />
                            </button>
                            {doc.status === "failed" && (
                              <button
                                onClick={() => handleRetry(doc)}
                                className="p-1.5 rounded-md hover:bg-slate-100 text-slate-400 hover:text-red-600 transition-colors"
                                title="Retry"
                              >
                                <RefreshCw className="w-3.5 h-3.5" />
                              </button>
                            )}
                            <button
                              onClick={() => handleTrash(doc)}
                              className="p-1.5 rounded-md hover:bg-slate-100 text-slate-400 hover:text-red-500 transition-colors"
                              title="Move to trash"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>

          {/* Pagination */}
          <div className="px-6 py-3 border-t border-slate-100 flex items-center justify-between">
            <p className="text-xs text-slate-400">
              {total} document{total !== 1 ? "s" : ""} total
            </p>
            {totalPages > 1 && (
              <div className="flex items-center gap-1">
                {Array.from({ length: Math.min(totalPages, 10) }, (_, i) => i + 1).map((p) => (
                  <button
                    key={p}
                    onClick={() => setPage(p)}
                    className={`w-7 h-7 rounded text-xs font-medium ${
                      p === page ? "bg-blue-600 text-white" : "text-slate-600 hover:bg-slate-100"
                    }`}
                  >
                    {p}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Grid pagination */}
      {viewMode === "grid" && totalPages > 1 && (
        <div className="mt-4 flex items-center justify-center gap-1">
          {Array.from({ length: Math.min(totalPages, 10) }, (_, i) => i + 1).map((p) => (
            <button
              key={p}
              onClick={() => setPage(p)}
              className={`w-7 h-7 rounded text-xs font-medium ${
                p === page ? "bg-blue-600 text-white" : "text-slate-600 hover:bg-slate-100"
              }`}
            >
              {p}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
