"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Search,
  SlidersHorizontal,
  FileText,
  FileImage,
  FileScan,
  Eye,
  Download,
  ChevronDown,
  X,
  Clock,
  Sparkles,
} from "lucide-react";
import { StatusBadge } from "@/components/status-badge";
import { mockDocuments, formatBytes, formatRelativeTime } from "@/lib/mock-data";
import type { Document, DocumentType } from "@/types";

const SUGGESTIONS = [
  "TNB invoice 2026",
  "contract Logistik Jaya",
  "LHDN notice",
  "parking receipt KLCC",
  "Q1 financial report",
];

const ALL_TYPES: DocumentType[] = [
  "invoice", "receipt", "contract", "report", "letter", "form", "other",
];

function highlight(text: string, query: string): React.ReactNode {
  if (!query.trim()) return text;
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx === -1) return text;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="bg-yellow-200 text-yellow-900 rounded px-0.5">{text.slice(idx, idx + query.length)}</mark>
      {text.slice(idx + query.length)}
    </>
  );
}

function DocIcon({ doc }: { doc: Document }) {
  if (doc.mimeType.startsWith("image/")) return <FileImage className="w-4 h-4 text-slate-400" />;
  if (!doc.hasTextLayer) return <FileScan className="w-4 h-4 text-slate-400" />;
  return <FileText className="w-4 h-4 text-slate-400" />;
}

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [typeFilter, setTypeFilter] = useState<DocumentType | "all">("all");
  const [dateFilter, setDateFilter] = useState<"any" | "today" | "week" | "month">("any");
  const [showFilters, setShowFilters] = useState(false);

  const handleSearch = (q: string) => {
    setQuery(q);
    setSubmitted(q);
  };

  const results = submitted
    ? mockDocuments.filter((d) => {
        const q = submitted.toLowerCase();
        const matchesQuery =
          d.originalFilename.toLowerCase().includes(q) ||
          d.tags.some((t) => t.toLowerCase().includes(q)) ||
          (d.extractedData &&
            JSON.stringify(d.extractedData).toLowerCase().includes(q)) ||
          d.documentType.includes(q) ||
          d.uploadedBy.toLowerCase().includes(q);
        const matchesType = typeFilter === "all" || d.documentType === typeFilter;
        return matchesQuery && matchesType;
      })
    : [];

  const clearSearch = () => {
    setQuery("");
    setSubmitted("");
  };

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-slate-900">Search</h1>
        <p className="text-slate-500 text-sm mt-0.5">
          Full-text search across filenames, extracted content, and metadata.
        </p>
      </div>

      {/* Search bar */}
      <div className="bg-white border border-slate-200 rounded-xl p-4 mb-4">
        <div className="flex gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleSearch(query); }}
              placeholder="Search documents, extracted data, tags…"
              className="w-full pl-11 pr-10 py-3 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-900 placeholder:text-slate-400"
            />
            {query && (
              <button
                onClick={clearSearch}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>
          <button
            onClick={() => handleSearch(query)}
            className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors"
          >
            Search
          </button>
          <button
            onClick={() => setShowFilters((v) => !v)}
            className={`flex items-center gap-2 px-4 py-2.5 border rounded-lg text-sm font-medium transition-colors ${
              showFilters
                ? "border-blue-400 text-blue-700 bg-blue-50"
                : "border-slate-200 text-slate-600 hover:bg-slate-50"
            }`}
          >
            <SlidersHorizontal className="w-4 h-4" />
            Filters
          </button>
        </div>

        {/* Filters panel */}
        {showFilters && (
          <div className="mt-4 pt-4 border-t border-slate-100 flex flex-wrap gap-4">
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Document type</p>
              <div className="flex flex-wrap gap-1.5">
                <button
                  onClick={() => setTypeFilter("all")}
                  className={`px-2.5 py-1 rounded-full text-xs border transition-colors ${
                    typeFilter === "all"
                      ? "bg-blue-600 text-white border-blue-600"
                      : "border-slate-200 text-slate-600 hover:border-blue-400"
                  }`}
                >
                  All
                </button>
                {ALL_TYPES.map((t) => (
                  <button
                    key={t}
                    onClick={() => setTypeFilter(t)}
                    className={`px-2.5 py-1 rounded-full text-xs border transition-colors capitalize ${
                      typeFilter === t
                        ? "bg-blue-600 text-white border-blue-600"
                        : "border-slate-200 text-slate-600 hover:border-blue-400"
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Date uploaded</p>
              <div className="relative">
                <select
                  value={dateFilter}
                  onChange={(e) => setDateFilter(e.target.value as typeof dateFilter)}
                  className="appearance-none pl-3 pr-8 py-1.5 rounded-lg border border-slate-200 text-xs text-slate-700 bg-white cursor-pointer focus:outline-none focus:ring-1 focus:ring-blue-500"
                >
                  <option value="any">Any time</option>
                  <option value="today">Today</option>
                  <option value="week">This week</option>
                  <option value="month">This month</option>
                </select>
                <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 text-slate-400 pointer-events-none" />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Suggestions (empty state) */}
      {!submitted && (
        <div>
          <div className="bg-white border border-slate-200 rounded-xl p-5 mb-4">
            <div className="flex items-center gap-2 mb-3">
              <Clock className="w-4 h-4 text-slate-400" />
              <span className="text-sm font-semibold text-slate-700">Suggested searches</span>
            </div>
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => handleSearch(s)}
                  className="px-3 py-1.5 bg-slate-100 hover:bg-blue-50 hover:text-blue-700 text-slate-600 rounded-full text-sm transition-colors border border-transparent hover:border-blue-200"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          <div className="bg-blue-50 border border-blue-200 rounded-xl p-5">
            <div className="flex items-center gap-2 mb-2">
              <Sparkles className="w-4 h-4 text-blue-600" />
              <span className="text-sm font-semibold text-blue-800">Search capabilities</span>
            </div>
            <ul className="space-y-1.5 text-sm text-blue-700">
              <li className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-blue-400 flex-shrink-0" />
                Fuzzy filename matching via <code className="text-xs bg-blue-100 px-1 rounded">pg_trgm</code>
              </li>
              <li className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-blue-400 flex-shrink-0" />
                Full-text content search via <code className="text-xs bg-blue-100 px-1 rounded">tsvector</code>
              </li>
              <li className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-blue-400 flex-shrink-0" />
                Structured data search via <code className="text-xs bg-blue-100 px-1 rounded">JSONB + GIN indexes</code>
              </li>
              <li className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-blue-400 flex-shrink-0" />
                Tag and metadata filtering
              </li>
            </ul>
          </div>
        </div>
      )}

      {/* Results */}
      {submitted && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <p className="text-sm text-slate-500">
              {results.length === 0
                ? "No results"
                : `${results.length} result${results.length > 1 ? "s" : ""}`}{" "}
              for <span className="font-medium text-slate-800">"{submitted}"</span>
            </p>
            {results.length > 0 && (
              <p className="text-xs text-slate-400">
                Search ran in ~4ms
              </p>
            )}
          </div>

          {results.length === 0 ? (
            <div className="bg-white border border-slate-200 rounded-xl p-10 text-center">
              <Search className="w-10 h-10 text-slate-200 mx-auto mb-3" />
              <p className="text-slate-500 font-medium">No documents found</p>
              <p className="text-slate-400 text-sm mt-1">
                Try different keywords, check filters, or upload the document first.
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {results.map((doc) => (
                <div
                  key={doc.id}
                  className="bg-white border border-slate-200 rounded-xl p-4 hover:border-blue-300 transition-colors group"
                >
                  <div className="flex items-start gap-4">
                    <div className="w-10 h-10 rounded-xl bg-slate-100 flex items-center justify-center flex-shrink-0 mt-0.5">
                      <DocIcon doc={doc} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-start justify-between gap-3 mb-1">
                        <Link
                          href={`/documents/${doc.id}`}
                          className="font-semibold text-slate-800 group-hover:text-blue-700 transition-colors truncate"
                        >
                          {highlight(doc.originalFilename, submitted)}
                        </Link>
                        <StatusBadge status={doc.status} />
                      </div>

                      {/* Snippet from extracted data */}
                      {doc.extractedData && (
                        <p className="text-xs text-slate-500 mb-2 line-clamp-1">
                          {highlight(
                            Object.entries(doc.extractedData)
                              .slice(0, 4)
                              .filter(([, v]) => typeof v === "string" || typeof v === "number")
                              .map(([k, v]) => `${k}: ${v}`)
                              .join(" · "),
                            submitted
                          )}
                        </p>
                      )}

                      <div className="flex items-center gap-3 flex-wrap">
                        <span className="text-xs text-slate-400 capitalize">{doc.documentType}</span>
                        <span className="text-slate-200">·</span>
                        <span className="text-xs text-slate-400">{formatBytes(doc.sizeBytes)}</span>
                        <span className="text-slate-200">·</span>
                        <span className="text-xs text-slate-400">{doc.uploadedBy}</span>
                        <span className="text-slate-200">·</span>
                        <span className="text-xs text-slate-400">{formatRelativeTime(doc.uploadedAt)}</span>

                        {doc.tags.slice(0, 3).map((tag) => (
                          <span
                            key={tag}
                            className="px-1.5 py-0.5 bg-slate-100 text-slate-500 rounded text-xs"
                          >
                            {highlight(tag, submitted)}
                          </span>
                        ))}
                      </div>
                    </div>

                    <div className="flex items-center gap-1 flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                      <Link
                        href={`/documents/${doc.id}`}
                        className="p-1.5 rounded-md hover:bg-slate-100 text-slate-400 hover:text-slate-700 transition-colors"
                      >
                        <Eye className="w-4 h-4" />
                      </Link>
                      <button className="p-1.5 rounded-md hover:bg-slate-100 text-slate-400 hover:text-slate-700 transition-colors">
                        <Download className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
