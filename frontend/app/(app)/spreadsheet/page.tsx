"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Table,
  Download,
  ChevronDown,
  ChevronUp,
  Loader2,
  TableIcon,
  AlertCircle,
  CheckSquare,
  Square,
} from "lucide-react";
import {
  downloadExportCsv,
  ExportFilters,
  ExportMeta,
  fetchExportFields,
  fetchExportMeta,
  fetchExportPreview,
} from "@/lib/api";

// ── Helpers ──────────────────────────────────────────────────────────────────

const STATUSES = [
  { value: "completed", label: "Completed" },
  { value: "needs_review", label: "Needs Review" },
  { value: "failed", label: "Failed" },
  { value: "queued", label: "Queued" },
];

function formatCellValue(val: unknown): string {
  if (val === null || val === undefined) return "";
  if (typeof val === "number") return val.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (typeof val === "boolean") return val ? "Yes" : "No";
  if (typeof val === "object") {
    try {
      return JSON.stringify(val);
    } catch {
      return "[object]";
    }
  }
  return String(val);
}

function ColHeader({ label }: { label: string }) {
  // Convert camelCase to Title Case with spaces
  const readable = label.replace(/([A-Z])/g, " $1").replace(/^./, (s) => s.toUpperCase());
  return (
    <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider whitespace-nowrap border-b border-slate-200 bg-slate-50">
      {readable}
    </th>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function SpreadsheetPage() {
  // --- Meta state (dropdowns) ---
  const [meta, setMeta] = useState<ExportMeta | null>(null);
  const [metaError, setMetaError] = useState<string | null>(null);

  // --- Filters ---
  const [docType, setDocType] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [status, setStatus] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [mode, setMode] = useState<"summary" | "expanded">("summary");

  // --- Column picker ---
  const [availableColumns, setAvailableColumns] = useState<string[]>([]);
  const [selectedColumns, setSelectedColumns] = useState<Set<string>>(new Set());
  const [columnsLoading, setColumnsLoading] = useState(false);

  // --- Preview ---
  const [previewRows, setPreviewRows] = useState<Record<string, unknown>[]>([]);
  const [previewTotal, setPreviewTotal] = useState(0);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  // --- Download ---
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  // --- Column section collapsed ---
  const [colSectionOpen, setColSectionOpen] = useState(true);

  // Derived: filtered templates based on selected docType
  const filteredTemplates = useMemo(() => {
    if (!meta) return [];
    if (!docType) return meta.templates;
    return meta.templates.filter((t) => t.documentType === docType);
  }, [meta, docType]);

  const filters: ExportFilters = useMemo(() => ({
    documentType: docType || undefined,
    templateId: templateId || undefined,
    status: status || undefined,
    dateFrom: dateFrom || undefined,
    dateTo: dateTo || undefined,
  }), [docType, templateId, status, dateFrom, dateTo]);

  // Build ordered columns for the table header
  const orderedColumns = useMemo(() => {
    // Always-present doc meta columns first
    const meta_cols = ["filename", "documentType", "status", "uploadedAt", "documentDate"];
    const extra = Array.from(selectedColumns).filter((c) => !meta_cols.includes(c));
    // Expanded-mode item columns at end
    const item_cols = mode === "expanded"
      ? ["depth", "itemDescription", "itemQuantity", "itemUnitPrice", "itemAmount"]
      : ["itemCount"];
    return [...meta_cols, ...extra, ...item_cols].filter((c) =>
      mode === "expanded"
        ? !["itemCount"].includes(c)
        : !["depth", "itemDescription", "itemQuantity", "itemUnitPrice", "itemAmount"].includes(c)
    );
  }, [selectedColumns, mode]);

  // ── Load meta on mount ────────────────────────────────────────────────────
  useEffect(() => {
    fetchExportMeta()
      .then(setMeta)
      .catch((e) => setMetaError(String(e)));
  }, []);

  // ── Fetch columns when filters change ────────────────────────────────────
  const loadColumns = useCallback(async () => {
    setColumnsLoading(true);
    setAvailableColumns([]);
    setPreviewRows([]);
    try {
      const cols = await fetchExportFields(filters);
      setAvailableColumns(cols);
      // Auto-select all new columns
      setSelectedColumns(new Set(cols));
    } catch {
      setAvailableColumns([]);
    } finally {
      setColumnsLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    loadColumns();
  }, [loadColumns]);

  // ── Fetch preview when columns or mode change ─────────────────────────────
  const loadPreview = useCallback(async () => {
    if (selectedColumns.size === 0) {
      setPreviewRows([]);
      setPreviewTotal(0);
      return;
    }
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      const result = await fetchExportPreview(filters, Array.from(selectedColumns), mode);
      setPreviewRows(result.rows.slice(0, 50)); // cap preview at 50 rows
      setPreviewTotal(result.total);
    } catch (e) {
      setPreviewError(String(e));
    } finally {
      setPreviewLoading(false);
    }
  }, [filters, selectedColumns, mode]);

  useEffect(() => {
    loadPreview();
  }, [loadPreview]);

  // ── Handlers ──────────────────────────────────────────────────────────────

  function handleDocTypeChange(val: string) {
    setDocType(val);
    // If selected template doesn't belong to this type, reset it
    if (templateId && meta) {
      const tpl = meta.templates.find((t) => t.id === templateId);
      if (tpl && tpl.documentType !== val) setTemplateId("");
    }
  }

  function handleTemplateChange(val: string) {
    setTemplateId(val);
    // Auto-lock doc type to match the template
    if (val && meta) {
      const tpl = meta.templates.find((t) => t.id === val);
      if (tpl) setDocType(tpl.documentType);
    }
  }

  function toggleColumn(col: string) {
    setSelectedColumns((prev) => {
      const next = new Set(prev);
      if (next.has(col)) next.delete(col);
      else next.add(col);
      return next;
    });
  }

  function selectAll() {
    setSelectedColumns(new Set(availableColumns));
  }

  function deselectAll() {
    setSelectedColumns(new Set());
  }

  async function handleDownload() {
    setDownloading(true);
    setDownloadError(null);
    try {
      await downloadExportCsv(filters, Array.from(selectedColumns), mode);
    } catch (e) {
      setDownloadError(String(e));
    } finally {
      setDownloading(false);
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800">
      {/* Page header */}
      <div className="sticky top-0 z-10 bg-white border-b border-slate-200 px-8 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-blue-600 flex items-center justify-center">
            <TableIcon className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-slate-900">Spreadsheet Center</h1>
            <p className="text-xs text-slate-500">
              Filter, select columns, and export your extracted document data
            </p>
          </div>
        </div>
        <button
          onClick={handleDownload}
          disabled={downloading || selectedColumns.size === 0}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors shadow-sm"
        >
          {downloading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Download className="w-4 h-4" />
          )}
          Download CSV
        </button>
      </div>

      {metaError && (
        <div className="mx-8 mt-6 p-4 rounded-lg bg-red-50 border border-red-200 text-red-700 flex items-center gap-2 text-sm">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          {metaError}
        </div>
      )}

      {downloadError && (
        <div className="mx-8 mt-6 p-4 rounded-lg bg-red-50 border border-red-200 text-red-700 flex items-center gap-2 text-sm">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          {downloadError}
        </div>
      )}

      <div className="p-8 space-y-6">

        {/* ── Filter bar ──────────────────────────────────────────────────── */}
        <section className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm space-y-4">
          <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wider">Filters</h2>

          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
            {/* Document Type */}
            <div className="flex flex-col gap-1">
              <label className="text-xs font-semibold text-slate-500">Document Type</label>
              <select
                value={docType}
                onChange={(e) => handleDocTypeChange(e.target.value)}
                className="bg-white border border-slate-300 rounded-lg px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-shadow"
              >
                <option value="">All Types</option>
                {meta?.documentTypes.map((dt) => (
                  <option key={dt.name} value={dt.name}>
                    {dt.name} {dt.count > 0 ? `(${dt.count})` : ""}
                  </option>
                ))}
              </select>
            </div>

            {/* Template */}
            <div className="flex flex-col gap-1">
              <label className="text-xs font-semibold text-slate-500">Template</label>
              <select
                value={templateId}
                onChange={(e) => handleTemplateChange(e.target.value)}
                className="bg-white border border-slate-300 rounded-lg px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-shadow"
              >
                <option value="">All Templates</option>
                {filteredTemplates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </div>

            {/* Status */}
            <div className="flex flex-col gap-1">
              <label className="text-xs font-semibold text-slate-500">Status</label>
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                className="bg-white border border-slate-300 rounded-lg px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-shadow"
              >
                <option value="">All Statuses</option>
                {STATUSES.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Date From */}
            <div className="flex flex-col gap-1">
              <label className="text-xs font-semibold text-slate-500">Date From</label>
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                className="bg-white border border-slate-300 rounded-lg px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-shadow"
              />
            </div>

            {/* Date To */}
            <div className="flex flex-col gap-1">
              <label className="text-xs font-semibold text-slate-500">Date To</label>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className="bg-white border border-slate-300 rounded-lg px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-shadow"
              />
            </div>
          </div>

          {/* Row mode */}
          <div className="flex items-center gap-4 pt-2 border-t border-slate-100">
            <span className="text-xs font-semibold text-slate-500">View Mode:</span>
            {(["summary", "expanded"] as const).map((m) => (
              <label key={m} className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="radio"
                  name="mode"
                  value={m}
                  checked={mode === m}
                  onChange={() => setMode(m)}
                  className="w-4 h-4 text-blue-600 border-slate-300 focus:ring-blue-500"
                />
                <span className="text-sm font-medium text-slate-700 capitalize">{m}</span>
                <span className="text-xs text-slate-400">
                  {m === "summary" ? "(1 row per document)" : "(1 row per line item)"}
                </span>
              </label>
            ))}
          </div>
        </section>

        {/* ── Column Picker ────────────────────────────────────────────────── */}
        <section className="bg-white rounded-xl border border-slate-200 shadow-sm">
          <div
            className="flex items-center justify-between px-5 py-4 cursor-pointer select-none border-b border-slate-100"
            onClick={() => setColSectionOpen((o) => !o)}
          >
            <div className="flex items-center gap-3">
              <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wider">
                Columns
              </h2>
              {columnsLoading ? (
                <Loader2 className="w-4 h-4 animate-spin text-slate-400" />
              ) : (
                <span className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full font-medium">
                  {selectedColumns.size} / {availableColumns.length} selected
                </span>
              )}
            </div>
            <div className="flex items-center gap-4">
              {!columnsLoading && availableColumns.length > 0 && (
                <div className="flex items-center gap-3">
                  <button
                    onClick={(e) => { e.stopPropagation(); selectAll(); }}
                    className="text-xs font-semibold text-blue-600 hover:text-blue-700 transition-colors"
                  >
                    Select All
                  </button>
                  <span className="w-px h-3 bg-slate-300" />
                  <button
                    onClick={(e) => { e.stopPropagation(); deselectAll(); }}
                    className="text-xs font-semibold text-slate-500 hover:text-slate-700 transition-colors"
                  >
                    Deselect All
                  </button>
                </div>
              )}
              {colSectionOpen ? (
                <ChevronUp className="w-5 h-5 text-slate-400" />
              ) : (
                <ChevronDown className="w-5 h-5 text-slate-400" />
              )}
            </div>
          </div>

          {colSectionOpen && (
            <div className="p-5">
              {columnsLoading ? (
                <div className="flex items-center gap-2 text-slate-400 text-sm py-2">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Loading available columns…
                </div>
              ) : availableColumns.length === 0 ? (
                <p className="text-slate-400 text-sm py-1 italic">
                  No columns found. Select a document type or template to see available fields.
                </p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {availableColumns.map((col) => {
                    const active = selectedColumns.has(col);
                    const label = col.replace(/([A-Z])/g, " $1").replace(/^./, (s) => s.toUpperCase());
                    return (
                      <button
                        key={col}
                        onClick={() => toggleColumn(col)}
                        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-medium transition-all ${
                          active
                            ? "bg-blue-50 border-blue-200 text-blue-700 shadow-sm"
                            : "bg-white border-slate-200 text-slate-600 hover:border-slate-350 hover:bg-slate-50"
                        }`}
                      >
                        {active ? (
                          <CheckSquare className="w-3.5 h-3.5 text-blue-600" />
                        ) : (
                          <Square className="w-3.5 h-3.5 text-slate-450" />
                        )}
                        {label}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </section>

        {/* ── Preview Table ────────────────────────────────────────────────── */}
        <section className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 bg-slate-50/50">
            <div className="flex items-center gap-3">
              <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wider">Preview</h2>
              {previewLoading ? (
                <Loader2 className="w-4 h-4 animate-spin text-slate-400" />
              ) : (
                <span className="text-xs bg-slate-200 text-slate-700 px-2 py-0.5 rounded-full font-medium">
                  {previewRows.length > 0
                    ? `Showing ${previewRows.length} of ${previewTotal} rows`
                    : "No data"}
                </span>
              )}
            </div>
            {previewTotal > 50 && (
              <span className="text-xs font-medium text-amber-600">
                Preview limited to 50 rows — download CSV for full data
              </span>
            )}
          </div>

          {previewError && (
            <div className="m-4 p-4 rounded-lg bg-red-50 border border-red-200 text-red-700 flex items-center gap-2 text-sm">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              {previewError}
            </div>
          )}

          {!previewLoading && previewRows.length === 0 && !previewError && (
            <div className="flex flex-col items-center justify-center py-20 text-slate-400 gap-3">
              <Table className="w-12 h-12 opacity-25" />
              <p className="text-sm font-medium">Select columns and filters to preview data</p>
            </div>
          )}

          {previewRows.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="bg-slate-50/50">
                    {orderedColumns.map((col) => (
                      <ColHeader key={col} label={col} />
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {previewRows.map((row, ri) => (
                    <tr
                      key={ri}
                      className={`hover:bg-slate-50/70 transition-colors ${
                        row.depth === 1 ? "bg-slate-50/30" : ""
                      }`}
                    >
                      {orderedColumns.map((col) => (
                        <td
                          key={col}
                          className={`px-4 py-3 text-slate-700 whitespace-nowrap max-w-[240px] truncate ${
                            col === "itemDescription" && row.depth === 1
                              ? "pl-8 text-slate-500 italic"
                              : ""
                          }`}
                          title={formatCellValue(row[col])}
                        >
                          {formatCellValue(row[col])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
