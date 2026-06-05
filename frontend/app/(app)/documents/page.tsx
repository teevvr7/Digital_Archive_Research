"use client";

import { useState } from "react";
import Link from "next/link";
import {
  FileText,
  FileImage,
  FileScan,
  Search,
  Filter,
  Upload,
  Download,
  Eye,
  RefreshCw,
  ChevronDown,
} from "lucide-react";
import { StatusBadge } from "@/components/status-badge";
import { mockDocuments, formatBytes, formatRelativeTime } from "@/lib/mock-data";
import type { Document, DocumentType, ProcessingStatus } from "@/types";

const ALL_STATUSES: ProcessingStatus[] = [
  "queued",
  "extracting_text",
  "ocr_processing",
  "ai_extraction",
  "completed",
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

function DocIcon({ doc }: { doc: Document }) {
  if (doc.mimeType.startsWith("image/"))
    return <FileImage className="w-4 h-4 text-slate-400" />;
  if (!doc.hasTextLayer)
    return <FileScan className="w-4 h-4 text-slate-400" />;
  return <FileText className="w-4 h-4 text-slate-400" />;
}

export default function DocumentsPage() {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<ProcessingStatus | "all">("all");
  const [typeFilter, setTypeFilter] = useState<DocumentType | "all">("all");
  const [sortBy, setSortBy] = useState<"date" | "name" | "size">("date");

  const filtered = mockDocuments
    .filter((d) => {
      const q = query.toLowerCase();
      return (
        (!q || d.originalFilename.toLowerCase().includes(q) || d.tags.some((t) => t.includes(q))) &&
        (statusFilter === "all" || d.status === statusFilter) &&
        (typeFilter === "all" || d.documentType === typeFilter)
      );
    })
    .sort((a, b) => {
      if (sortBy === "date")
        return new Date(b.uploadedAt).getTime() - new Date(a.uploadedAt).getTime();
      if (sortBy === "name")
        return a.originalFilename.localeCompare(b.originalFilename);
      return b.sizeBytes - a.sizeBytes;
    });

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Documents</h1>
          <p className="text-slate-500 text-sm mt-0.5">
            {mockDocuments.length} documents · {filtered.length} shown
          </p>
        </div>
        <Link
          href="/upload"
          className="inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2.5 rounded-lg text-sm font-medium transition-colors"
        >
          <Upload className="w-4 h-4" />
          Upload
        </Link>
      </div>

      {/* Filters */}
      <div className="bg-white border border-slate-200 rounded-xl p-4 mb-4 flex flex-wrap gap-3 items-center">
        {/* Search */}
        <div className="relative flex-1 min-w-52">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by filename or tag…"
            className="w-full pl-9 pr-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-900 placeholder:text-slate-400"
          />
        </div>

        {/* Status filter */}
        <div className="relative">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as ProcessingStatus | "all")}
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

        {/* Type filter */}
        <div className="relative">
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as DocumentType | "all")}
            className="appearance-none pl-3 pr-8 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-700 bg-white cursor-pointer"
          >
            <option value="all">All Types</option>
            {ALL_TYPES.map((t) => (
              <option key={t} value={t}>
                {t.charAt(0).toUpperCase() + t.slice(1)}
              </option>
            ))}
          </select>
          <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
        </div>

        {/* Sort */}
        <div className="relative">
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as "date" | "name" | "size")}
            className="appearance-none pl-3 pr-8 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-700 bg-white cursor-pointer"
          >
            <option value="date">Newest first</option>
            <option value="name">Name A–Z</option>
            <option value="size">Largest first</option>
          </select>
          <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
        </div>

        <button className="flex items-center gap-1.5 px-3 py-2 border border-slate-200 rounded-lg text-sm text-slate-600 hover:bg-slate-50 transition-colors">
          <Filter className="w-3.5 h-3.5" />
          Filters
        </button>
      </div>

      {/* Table */}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 bg-slate-50">
              <th className="text-left px-6 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Document</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Type</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Status</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Uploaded</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Size</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Pages</th>
              <th className="text-right px-6 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-50">
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-6 py-12 text-center text-slate-400 text-sm">
                  No documents match your filters.
                </td>
              </tr>
            ) : (
              filtered.map((doc) => (
                <tr key={doc.id} className="hover:bg-slate-50 transition-colors group">
                  <td className="px-6 py-3.5">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 bg-slate-100 rounded-lg flex items-center justify-center flex-shrink-0">
                        <DocIcon doc={doc} />
                      </div>
                      <div className="min-w-0">
                        <Link
                          href={`/documents/${doc.id}`}
                          className="font-medium text-slate-800 group-hover:text-blue-700 truncate block max-w-xs"
                        >
                          {doc.originalFilename}
                        </Link>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          {doc.tags.slice(0, 3).map((tag) => (
                            <span key={tag} className="px-1.5 py-0.5 bg-slate-100 text-slate-500 rounded text-xs">
                              {tag}
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
                  </td>
                  <td className="px-4 py-3.5 text-slate-500 text-xs">{formatBytes(doc.sizeBytes)}</td>
                  <td className="px-4 py-3.5 text-slate-500 text-xs">
                    {doc.pageCount ?? "—"}
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
                      <button
                        className="p-1.5 rounded-md hover:bg-slate-100 text-slate-400 hover:text-slate-700 transition-colors"
                        title="Download"
                      >
                        <Download className="w-3.5 h-3.5" />
                      </button>
                      {doc.status === "failed" && (
                        <button
                          className="p-1.5 rounded-md hover:bg-slate-100 text-slate-400 hover:text-red-600 transition-colors"
                          title="Retry"
                        >
                          <RefreshCw className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>

        {/* Pagination stub */}
        <div className="px-6 py-3 border-t border-slate-100 flex items-center justify-between">
          <p className="text-xs text-slate-400">Showing {filtered.length} of {mockDocuments.length} documents</p>
          <div className="flex items-center gap-1">
            {[1].map((p) => (
              <button
                key={p}
                className="w-7 h-7 rounded text-xs bg-blue-600 text-white font-medium"
              >
                {p}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
