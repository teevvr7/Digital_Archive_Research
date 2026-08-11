"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
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
import { useAuth } from "@/lib/auth";
import { StatusBadge } from "@/components/status-badge";
import { daysUntilTrashPurge, formatBytes, formatRelativeTime } from "@/lib/format";
import {
  apiDocuments,
  apiDownloadUrl,
  apiExtractMissing,
  apiRetryDocument,
  apiTrashDocument,
  apiRestoreDocument,
  apiEmptyTrash,
  apiPermanentDelete,
  apiTags,
  apiCorrespondents,
  apiThumbnailUrl,
  apiSavedViews,
  apiCreateSavedView,
  apiBulkTrash,
  apiBulkTag,
  apiBulkSetType,
  apiExportDocuments,
  apiBulkDownload,
  apiPredefinedFields,
  type DocumentListResponse,
} from "@/lib/api";
import { CustomFieldInput } from "@/components/custom-field-input";
import { useToast } from "@/components/ui/toast";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { TableRowsSkeleton, CardGridSkeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import type {
  Correspondent,
  Document,
  DocumentType,
  PredefinedField,
  ProcessingStatus,
  SavedView,
  Tag,
} from "@/types";

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

function DocumentsPageInner() {
  const { tenant, refresh: refreshAuth } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const toast = useToast();
  const confirm = useConfirm();

  // ---- Filters ----
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<ProcessingStatus | "all">("all");
  const [typeFilter, setTypeFilter] = useState<DocumentType | "all">("all");
  const [tagFilter, setTagFilter] = useState<string>("all");
  const [correspondentFilter, setCorrespondentFilter] = useState<string>("all");
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");
  const [vendorFilter, setVendorFilter] = useState<string>("");
  const [amountMin, setAmountMin] = useState<string>("");
  const [amountMax, setAmountMax] = useState<string>("");
  const [inbox, setInbox] = useState(false);
  const [sortBy, setSortBy] = useState("date_desc");
  const [page, setPage] = useState(1);
  const [trashed, setTrashed] = useState(false);

  // Custom-field filter — gated behind typeFilter (only fields predefined
  // for the selected type are offered), so it never has to show a tenant's
  // entire field catalog at once.
  const [customFieldId, setCustomFieldId] = useState<string>("all");
  const [customFieldValue, setCustomFieldValue] = useState<string>("");
  const [customFieldMin, setCustomFieldMin] = useState<string>("");
  const [customFieldMax, setCustomFieldMax] = useState<string>("");
  const [customFieldDateFrom, setCustomFieldDateFrom] = useState<string>("");
  const [customFieldDateTo, setCustomFieldDateTo] = useState<string>("");
  // A number field can be a real quantity (Amount) or a reference number
  // someone only half-remembers (Order Number) — "contains" lets the latter
  // be found by typing a few digits instead of guessing a min/max range.
  const [customFieldNumberMode, setCustomFieldNumberMode] = useState<"contains" | "range">(
    "contains"
  );

  // ---- View ----
  const [viewMode, setViewMode] = useState<"table" | "grid">("table");

  // ---- Data ----
  const [data, setData] = useState<DocumentListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [allTags, setAllTags] = useState<Tag[]>([]);
  const [allCorrespondents, setAllCorrespondents] = useState<Correspondent[]>([]);
  const [predefinedFields, setPredefinedFields] = useState<Record<string, PredefinedField[]>>({});
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
  const [exporting, setExporting] = useState(false);
  const [showExportMenu, setShowExportMenu] = useState(false);

  const bulkTagRef = useRef<HTMLDivElement>(null);
  const bulkTypeRef = useRef<HTMLDivElement>(null);
  const exportMenuRef = useRef<HTMLDivElement>(null);

  // Bumped by every fetch (initial load, poll tick) and every optimistic
  // single-doc mutation. A fetch only applies its response if the counter
  // hasn't moved since it started — otherwise a poll response that was
  // already in flight when e.g. a permanent-delete's optimistic update
  // landed can silently overwrite it with stale data a moment later.
  const dataGenerationRef = useRef(0);

  // Load static lists once
  useEffect(() => {
    apiTags().then(setAllTags).catch(() => {});
    apiCorrespondents().then(setAllCorrespondents).catch(() => {});
    apiSavedViews().then(setSavedViews).catch(() => {});
    apiPredefinedFields().then(setPredefinedFields).catch(() => {});
  }, []);

  // Seed filter state from the URL's own query string — e.g. the sidebar's
  // "Inbox" link (`/documents?inbox=true`) or a saved view's "open" link.
  // Depends on `searchParams` (not just mount) because a soft Link navigation
  // between two /documents-family URLs (e.g. clicking "Inbox" while already
  // on this page) doesn't remount the component — a mount-only effect would
  // silently miss the new query string. searchParams only changes on a real
  // navigation, never from this page's own local filter-state changes (which
  // don't push to the URL), so this can't loop or fight user-driven filtering.
  useEffect(() => {
    if (searchParams.get("inbox") === "true") setInbox(true);
    if (searchParams.get("status")) setStatusFilter(searchParams.get("status") as ProcessingStatus);
    if (searchParams.get("type")) setTypeFilter(searchParams.get("type") as DocumentType);
    if (searchParams.get("tag_id")) setTagFilter(searchParams.get("tag_id")!);
    if (searchParams.get("correspondent_id")) setCorrespondentFilter(searchParams.get("correspondent_id")!);
    if (searchParams.get("date_from")) setDateFrom(searchParams.get("date_from")!);
    if (searchParams.get("date_to")) setDateTo(searchParams.get("date_to")!);
    if (searchParams.get("vendor")) setVendorFilter(searchParams.get("vendor")!);
    if (searchParams.get("amount_min")) setAmountMin(searchParams.get("amount_min")!);
    if (searchParams.get("amount_max")) setAmountMax(searchParams.get("amount_max")!);
    if (searchParams.get("q")) setQuery(searchParams.get("q")!);
    if (searchParams.get("sort")) setSortBy(searchParams.get("sort")!);
    if (searchParams.get("custom_field_id")) setCustomFieldId(searchParams.get("custom_field_id")!);
    if (searchParams.get("custom_field_value")) setCustomFieldValue(searchParams.get("custom_field_value")!);
    if (searchParams.get("custom_field_min")) setCustomFieldMin(searchParams.get("custom_field_min")!);
    if (searchParams.get("custom_field_max")) setCustomFieldMax(searchParams.get("custom_field_max")!);
    if (searchParams.get("custom_field_date_from")) setCustomFieldDateFrom(searchParams.get("custom_field_date_from")!);
    if (searchParams.get("custom_field_date_to")) setCustomFieldDateTo(searchParams.get("custom_field_date_to")!);
    if (searchParams.get("custom_field_number_mode")) {
      setCustomFieldNumberMode(searchParams.get("custom_field_number_mode") as "contains" | "range");
    }
  }, [searchParams]);

  // Close bulk menus on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (bulkTagRef.current && !bulkTagRef.current.contains(e.target as Node))
        setShowBulkTagMenu(false);
      if (bulkTypeRef.current && !bulkTypeRef.current.contains(e.target as Node))
        setShowBulkTypeMenu(false);
      if (exportMenuRef.current && !exportMenuRef.current.contains(e.target as Node))
        setShowExportMenu(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // The field the custom-field picker resolves to, scoped to the selected
  // type — used to decide which value/range inputs to render and send.
  const selectedCustomField: PredefinedField | undefined =
    typeFilter !== "all"
      ? predefinedFields[typeFilter]?.find((f) => f.fieldId === customFieldId)
      : undefined;

  const buildQuery = () => ({
    status: statusFilter === "all" ? undefined : statusFilter,
    type: typeFilter === "all" ? undefined : typeFilter,
    tag_id: tagFilter !== "all" ? tagFilter : undefined,
    correspondent_id: correspondentFilter !== "all" ? correspondentFilter : undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    vendor: vendorFilter || undefined,
    amount_min: amountMin ? Number(amountMin) : undefined,
    amount_max: amountMax ? Number(amountMax) : undefined,
    inbox: inbox || undefined,
    q: query || undefined,
    sort: sortBy,
    page,
    trashed: trashed || undefined,
    custom_field_id: selectedCustomField ? customFieldId : undefined,
    custom_field_value:
      selectedCustomField &&
      (selectedCustomField.fieldType === "text" ||
        selectedCustomField.fieldType === "select" ||
        selectedCustomField.fieldType === "boolean" ||
        (selectedCustomField.fieldType === "number" && customFieldNumberMode === "contains")) &&
      customFieldValue
        ? customFieldValue
        : undefined,
    custom_field_min:
      selectedCustomField?.fieldType === "number" &&
      customFieldNumberMode === "range" &&
      customFieldMin
        ? Number(customFieldMin)
        : undefined,
    custom_field_max:
      selectedCustomField?.fieldType === "number" &&
      customFieldNumberMode === "range" &&
      customFieldMax
        ? Number(customFieldMax)
        : undefined,
    custom_field_date_from:
      selectedCustomField?.fieldType === "date" && customFieldDateFrom
        ? customFieldDateFrom
        : undefined,
    custom_field_date_to:
      selectedCustomField?.fieldType === "date" && customFieldDateTo
        ? customFieldDateTo
        : undefined,
  });

  const refreshDocuments = () => {
    setLoading(true);
    setError("");
    const gen = ++dataGenerationRef.current;
    apiDocuments(buildQuery())
      .then((d) => {
        if (gen !== dataGenerationRef.current) return; // superseded by a newer fetch/mutation
        setData(d);
        setSelectedIds(new Set());
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  };

  const filterDeps = [
    statusFilter, typeFilter, tagFilter, correspondentFilter, dateFrom, dateTo,
    vendorFilter, amountMin, amountMax,
    inbox, sortBy, page, query, trashed,
    customFieldId, customFieldValue, customFieldMin, customFieldMax,
    customFieldDateFrom, customFieldDateTo, customFieldNumberMode,
  ];

  useEffect(() => {
    refreshDocuments();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, filterDeps);

  // Silent poll while any doc is still processing
  useEffect(() => {
    const hasInProgress = data?.items.some((d) => !TERMINAL_STATUSES.has(d.status));
    if (!hasInProgress) return;
    const timerId = setInterval(() => {
      const gen = ++dataGenerationRef.current;
      apiDocuments(buildQuery())
        .then((d) => {
          if (gen !== dataGenerationRef.current) return; // superseded by a newer fetch/mutation
          setData(d);
        })
        .catch(() => {});
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timerId);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, ...filterDeps]);

  const docs = data?.items ?? [];
  const total = data?.total ?? 0;
  const pageSize = data?.pageSize ?? 20;
  const totalPages = Math.ceil(total / pageSize);

  // ---- Filter helpers ----
  const resetCustomFieldFilter = () => {
    setCustomFieldId("all");
    setCustomFieldValue("");
    setCustomFieldMin("");
    setCustomFieldMax("");
    setCustomFieldDateFrom("");
    setCustomFieldDateTo("");
    setCustomFieldNumberMode("contains");
  };

  const resetFilters = () => {
    setQuery("");
    setStatusFilter("all");
    setTypeFilter("all");
    setTagFilter("all");
    setCorrespondentFilter("all");
    setDateFrom("");
    setDateTo("");
    setVendorFilter("");
    setAmountMin("");
    setAmountMax("");
    setInbox(false);
    setSortBy("date_desc");
    setPage(1);
    resetCustomFieldFilter();
  };

  const hasActiveFilters =
    query || statusFilter !== "all" || typeFilter !== "all" || tagFilter !== "all" ||
    correspondentFilter !== "all" || dateFrom || dateTo || vendorFilter || amountMin || amountMax ||
    inbox || customFieldId !== "all";

  const emptyStateProps = trashed
    ? {
        icon: Trash2,
        title: "Trash is empty",
        description: "Documents you move to trash will show up here.",
      }
    : hasActiveFilters
      ? {
          icon: Search,
          title: "No documents match these filters",
          description: "Try adjusting or clearing your filters.",
          action: { label: "Clear filters", onClick: resetFilters },
        }
      : {
          icon: Upload,
          title: "No documents yet",
          description: "Upload your first document to get started.",
          action: { label: "Upload", onClick: () => router.push("/upload") },
        };

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
    setVendorFilter((s.vendor as string) || "");
    setAmountMin(s.amount_min !== undefined ? String(s.amount_min) : "");
    setAmountMax(s.amount_max !== undefined ? String(s.amount_max) : "");
    setInbox(Boolean(s.inbox));
    setSortBy((s.sort as string) || "date_desc");
    setPage(1);
    setCustomFieldId((s.custom_field_id as string) || "all");
    setCustomFieldValue((s.custom_field_value as string) || "");
    setCustomFieldMin(s.custom_field_min !== undefined ? String(s.custom_field_min) : "");
    setCustomFieldMax(s.custom_field_max !== undefined ? String(s.custom_field_max) : "");
    setCustomFieldDateFrom((s.custom_field_date_from as string) || "");
    setCustomFieldDateTo((s.custom_field_date_to as string) || "");
    setCustomFieldNumberMode((s.custom_field_number_mode as "contains" | "range") || "contains");
  };

  const currentFilterState = () => ({
    ...(query && { q: query }),
    ...(statusFilter !== "all" && { status: statusFilter }),
    ...(typeFilter !== "all" && { type: typeFilter }),
    ...(tagFilter !== "all" && { tag_id: tagFilter }),
    ...(correspondentFilter !== "all" && { correspondent_id: correspondentFilter }),
    ...(dateFrom && { date_from: dateFrom }),
    ...(dateTo && { date_to: dateTo }),
    ...(vendorFilter && { vendor: vendorFilter }),
    ...(amountMin && { amount_min: Number(amountMin) }),
    ...(amountMax && { amount_max: Number(amountMax) }),
    ...(inbox && { inbox: true }),
    ...(sortBy !== "date_desc" && { sort: sortBy }),
    ...(customFieldId !== "all" && { custom_field_id: customFieldId }),
    ...(customFieldValue && { custom_field_value: customFieldValue }),
    ...(customFieldMin && { custom_field_min: Number(customFieldMin) }),
    ...(customFieldMax && { custom_field_max: Number(customFieldMax) }),
    ...(customFieldDateFrom && { custom_field_date_from: customFieldDateFrom }),
    ...(customFieldDateTo && { custom_field_date_to: customFieldDateTo }),
    ...(customFieldNumberMode !== "contains" && { custom_field_number_mode: customFieldNumberMode }),
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
      toast.success(`Saved view "${created.name}".`);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed to save view");
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
    const count = selectedIds.size;
    const ok = await confirm({
      title: "Move to trash?",
      body: `Move ${count} document${count !== 1 ? "s" : ""} to trash?`,
      confirmLabel: "Move to trash",
      danger: true,
    });
    if (!ok) return;
    setBulkLoading(true);
    try {
      await apiBulkTrash([...selectedIds]);
      setSelectedIds(new Set());
      refreshDocuments();
      toast.success(`Moved ${count} document${count !== 1 ? "s" : ""} to trash.`);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Bulk trash failed");
    } finally {
      setBulkLoading(false);
    }
  };

  const handleBulkDownload = async () => {
    setBulkLoading(true);
    try {
      await apiBulkDownload([...selectedIds]);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Bulk download failed");
    } finally {
      setBulkLoading(false);
    }
  };

  const handleExport = async (format: "csv" | "xlsx") => {
    setExporting(true);
    try {
      const { truncated } = await apiExportDocuments(buildQuery(), format);
      if (truncated) {
        toast.info(
          `Export capped at the first 5,000 matching documents — narrow your filters to get everything.`
        );
      } else {
        toast.success("Export ready — check your downloads.");
      }
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Export failed");
    } finally {
      setExporting(false);
    }
  };

  const handleBulkTag = async (tagId: string, action: "assign" | "remove") => {
    const count = selectedIds.size;
    setBulkLoading(true);
    setShowBulkTagMenu(false);
    try {
      await apiBulkTag([...selectedIds], tagId, action);
      refreshDocuments();
      toast.success(`Tag ${action === "assign" ? "assigned to" : "removed from"} ${count} document${count !== 1 ? "s" : ""}.`);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Bulk tag failed");
    } finally {
      setBulkLoading(false);
    }
  };

  const handleBulkSetType = async (docType: string) => {
    const count = selectedIds.size;
    setBulkLoading(true);
    setShowBulkTypeMenu(false);
    try {
      await apiBulkSetType([...selectedIds], docType);
      refreshDocuments();
      toast.success(`Type set to "${docType}" for ${count} document${count !== 1 ? "s" : ""}.`);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Bulk set type failed");
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
      toast.error(e instanceof Error ? e.message : "Download failed");
    }
  };

  const handleRetry = async (doc: Document) => {
    try {
      await apiRetryDocument(doc.id);
      setPage((p) => p);
      toast.success("Retry queued.");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Retry failed");
    }
  };

  const handleTrash = async (doc: Document) => {
    try {
      await apiTrashDocument(doc.id);
      // Invalidate any poll/fetch already in flight before this mutation, so
      // its response can't land afterward and silently undo this update.
      dataGenerationRef.current++;
      setData((d) => d ? { ...d, items: d.items.filter((i) => i.id !== doc.id), total: d.total - 1 } : d);
      toast.success("Moved to trash.");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Move to trash failed");
    }
  };

  const handleRestore = async (doc: Document) => {
    try {
      await apiRestoreDocument(doc.id);
      dataGenerationRef.current++;
      setData((d) => d ? { ...d, items: d.items.filter((i) => i.id !== doc.id), total: d.total - 1 } : d);
      toast.success("Restored from trash.");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Restore failed");
    }
  };

  const handleEmptyTrash = async () => {
    const ok = await confirm({
      title: "Empty trash?",
      body: "Permanently delete all trashed documents? This cannot be undone.",
      confirmLabel: "Delete permanently",
      danger: true,
    });
    if (!ok) return;
    setEmptyingTrash(true);
    try {
      const { deleted } = await apiEmptyTrash();
      toast.success(`Permanently deleted ${deleted} document${deleted !== 1 ? "s" : ""}.`);
      refreshDocuments();
      // Freed real storage — the sidebar's tenant snapshot won't know unless told.
      refreshAuth();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed to empty trash");
    } finally {
      setEmptyingTrash(false);
    }
  };

  const handlePermanentDelete = async (doc: Document) => {
    const ok = await confirm({
      title: "Delete permanently?",
      body: `Permanently delete "${doc.title || doc.originalFilename}"? This cannot be undone.`,
      confirmLabel: "Delete permanently",
      danger: true,
    });
    if (!ok) return;
    try {
      await apiPermanentDelete(doc.id);
      dataGenerationRef.current++;
      setData((d) => d ? { ...d, items: d.items.filter((i) => i.id !== doc.id), total: d.total - 1 } : d);
      toast.success("Document permanently deleted.");
      // Freed real storage — the sidebar's tenant snapshot won't know unless told.
      refreshAuth();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Permanent delete failed");
    }
  };

  const handleExtractMissing = async () => {
    setExtractingMissing(true);
    try {
      const { enqueued } = await apiExtractMissing();
      toast.success(`Queued AI extraction for ${enqueued} document${enqueued !== 1 ? "s" : ""}.`);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed to queue extraction");
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
                  data-testid="bulk-tag-button"
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
                data-testid="bulk-set-type-button"
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

            <button
              data-testid="bulk-download-button"
              onClick={handleBulkDownload}
              disabled={bulkLoading || selectedIds.size > 100}
              title={selectedIds.size > 100 ? "Download at most 100 files at a time" : "Download originals as a zip"}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 text-sm rounded-lg disabled:opacity-50"
            >
              {bulkLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
              Download
            </button>

            {!trashed && (
              <button
                data-testid="bulk-trash-button"
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
              data-testid="type-filter"
              value={typeFilter}
              onChange={(e) => {
                setTypeFilter(e.target.value as DocumentType | "all");
                setPage(1);
                // The custom-field picker is scoped to the selected type — a
                // field picked for the old type may not exist for the new one.
                resetCustomFieldFilter();
              }}
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

          <input
            type="text"
            placeholder="Vendor…"
            value={vendorFilter}
            onChange={(e) => { setVendorFilter(e.target.value); setPage(1); }}
            className="w-32 px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-700 placeholder:text-slate-400"
            title="Filter by vendor name"
          />
          <input
            type="number"
            inputMode="decimal"
            placeholder="Min amount"
            value={amountMin}
            onChange={(e) => { setAmountMin(e.target.value); setPage(1); }}
            className="w-28 px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-700 placeholder:text-slate-400"
            title="Minimum total amount"
          />
          <span className="text-slate-400 text-sm">→</span>
          <input
            type="number"
            inputMode="decimal"
            placeholder="Max amount"
            value={amountMax}
            onChange={(e) => { setAmountMax(e.target.value); setPage(1); }}
            className="w-28 px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-700 placeholder:text-slate-400"
            title="Maximum total amount"
          />

          {/* Custom-field filter — only unlocks once a Type is picked, and
              only offers fields predefined for that type (never the whole
              tenant catalog at once). */}
          {typeFilter !== "all" && (predefinedFields[typeFilter]?.length ?? 0) > 0 && (
            <>
              <div className="relative">
                <select
                  data-testid="custom-field-picker"
                  value={customFieldId}
                  onChange={(e) => {
                    setCustomFieldId(e.target.value);
                    setCustomFieldValue("");
                    setCustomFieldMin("");
                    setCustomFieldMax("");
                    setCustomFieldDateFrom("");
                    setCustomFieldDateTo("");
                    setCustomFieldNumberMode("contains");
                    setPage(1);
                  }}
                  className="appearance-none pl-3 pr-8 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-700 bg-white cursor-pointer"
                >
                  <option value="all">Any custom field</option>
                  {predefinedFields[typeFilter].map((f) => (
                    <option key={f.fieldId} value={f.fieldId}>{f.fieldName}</option>
                  ))}
                </select>
                <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
              </div>

              {selectedCustomField && (
                selectedCustomField.fieldType === "number" ? (
                  <>
                    <div className="inline-flex rounded-lg border border-slate-200 overflow-hidden text-xs flex-shrink-0">
                      <button
                        type="button"
                        onClick={() => { setCustomFieldNumberMode("contains"); setPage(1); }}
                        className={`px-2.5 py-2 font-medium transition-colors ${
                          customFieldNumberMode === "contains"
                            ? "bg-blue-600 text-white"
                            : "bg-white text-slate-500 hover:bg-slate-50"
                        }`}
                        title="Find by typing part of the number (e.g. an order number you half-remember)"
                      >
                        Contains
                      </button>
                      <button
                        type="button"
                        onClick={() => { setCustomFieldNumberMode("range"); setPage(1); }}
                        className={`px-2.5 py-2 font-medium border-l border-slate-200 transition-colors ${
                          customFieldNumberMode === "range"
                            ? "bg-blue-600 text-white"
                            : "bg-white text-slate-500 hover:bg-slate-50"
                        }`}
                        title="Filter by a min/max range (for quantities/amounts)"
                      >
                        Range
                      </button>
                    </div>
                    {customFieldNumberMode === "contains" ? (
                      <input
                        type="text"
                        inputMode="numeric"
                        placeholder="Contains…"
                        value={customFieldValue}
                        onChange={(e) => { setCustomFieldValue(e.target.value); setPage(1); }}
                        className="w-28 px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-700 placeholder:text-slate-400"
                      />
                    ) : (
                      <>
                        <input
                          type="number"
                          inputMode="decimal"
                          placeholder="Min"
                          value={customFieldMin}
                          onChange={(e) => { setCustomFieldMin(e.target.value); setPage(1); }}
                          className="w-20 px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-700 placeholder:text-slate-400"
                        />
                        <span className="text-slate-400 text-sm">→</span>
                        <input
                          type="number"
                          inputMode="decimal"
                          placeholder="Max"
                          value={customFieldMax}
                          onChange={(e) => { setCustomFieldMax(e.target.value); setPage(1); }}
                          className="w-20 px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-700 placeholder:text-slate-400"
                        />
                      </>
                    )}
                  </>
                ) : selectedCustomField.fieldType === "date" ? (
                  <>
                    <input
                      type="date"
                      value={customFieldDateFrom}
                      onChange={(e) => { setCustomFieldDateFrom(e.target.value); setPage(1); }}
                      className="px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-700"
                    />
                    <span className="text-slate-400 text-sm">→</span>
                    <input
                      type="date"
                      value={customFieldDateTo}
                      onChange={(e) => { setCustomFieldDateTo(e.target.value); setPage(1); }}
                      className="px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-700"
                    />
                  </>
                ) : (
                  <div className="w-36">
                    <CustomFieldInput
                      fieldType={selectedCustomField.fieldType}
                      options={selectedCustomField.options}
                      value={customFieldValue}
                      onChange={(v) => { setCustomFieldValue(v); setPage(1); }}
                      className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-700 bg-white"
                    />
                  </div>
                )
              )}
            </>
          )}

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
            <div className="relative" ref={exportMenuRef}>
              <button
                onClick={() => setShowExportMenu((v) => !v)}
                disabled={exporting}
                className="flex items-center gap-1.5 px-3 py-2 text-sm text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-50"
                title="Export the current filtered list"
              >
                {exporting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
                Export
                <ChevronDown className="w-3 h-3" />
              </button>
              {showExportMenu && (
                <div className="absolute top-full right-0 mt-1 z-20 bg-white border border-slate-200 rounded-xl shadow-lg min-w-32 py-1">
                  <button
                    onClick={() => { setShowExportMenu(false); handleExport("csv"); }}
                    className="w-full text-left px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
                  >
                    CSV
                  </button>
                  <button
                    onClick={() => { setShowExportMenu(false); handleExport("xlsx"); }}
                    className="w-full text-left px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
                  >
                    Excel (.xlsx)
                  </button>
                </div>
              )}
            </div>
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
        viewMode === "grid" ? <CardGridSkeleton /> : <TableRowsSkeleton />
      ) : viewMode === "grid" ? (
        <>
          {docs.length === 0 ? (
            <EmptyState {...emptyStateProps} />
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
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
        <div className="bg-white border border-slate-200 rounded-xl overflow-x-auto">
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
                  <td colSpan={7} className="p-0">
                    <EmptyState {...emptyStateProps} />
                  </td>
                </tr>
              ) : (
                docs.map((doc) => {
                  const daysLeft =
                    trashed && doc.deletedAt
                      ? daysUntilTrashPurge(doc.deletedAt, tenant?.effectiveTrashRetentionDays ?? 30)
                      : null;
                  return (
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
                            {daysLeft !== null && (
                              <span
                                className="text-xs text-red-500"
                                title="Automatically deleted forever once the retention window elapses"
                              >
                                Purges in {daysLeft} {daysLeft === 1 ? "day" : "days"}
                              </span>
                            )}
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
                      <div className="text-slate-400">{doc.uploadedAt.split("T")[0]}</div>
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
                          <>
                            <button
                              onClick={() => handleRestore(doc)}
                              className="p-1.5 rounded-md hover:bg-slate-100 text-slate-400 hover:text-green-600 transition-colors"
                              title="Restore"
                            >
                              <RotateCcw className="w-3.5 h-3.5" />
                            </button>
                            <button
                              onClick={() => handlePermanentDelete(doc)}
                              className="p-1.5 rounded-md hover:bg-red-50 text-slate-400 hover:text-red-600 transition-colors"
                              title="Delete permanently"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </>
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
                  );
                })
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

/**
 * Next 16 requires any `useSearchParams()` consumer to sit under a Suspense
 * boundary, otherwise the route de-opts to full client rendering (and the
 * build errors) — same pattern as `app/login/page.tsx`.
 */
export default function DocumentsPage() {
  return (
    <Suspense fallback={null}>
      <DocumentsPageInner />
    </Suspense>
  );
}
