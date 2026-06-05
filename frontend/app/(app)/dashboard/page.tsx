"use client";

import Link from "next/link";
import {
  FileText,
  Upload,
  CheckCircle2,
  AlertCircle,
  TrendingUp,
  Clock,
  ArrowUpRight,
  FileImage,
  FileScan,
} from "lucide-react";
import { StatusBadge } from "@/components/status-badge";
import {
  mockDocuments,
  mockActivity,
  mockTenant,
  storagePercent,
  formatBytes,
  formatRelativeTime,
} from "@/lib/mock-data";
import type { ActivityEvent } from "@/types";

const completed = mockDocuments.filter((d) => d.status === "completed").length;
const processing = mockDocuments.filter(
  (d) => !["completed", "failed"].includes(d.status)
).length;
const failed = mockDocuments.filter((d) => d.status === "failed").length;
const recentDocs = [...mockDocuments].sort(
  (a, b) => new Date(b.uploadedAt).getTime() - new Date(a.uploadedAt).getTime()
).slice(0, 5);

function ActivityIcon({ type }: { type: ActivityEvent["type"] }) {
  switch (type) {
    case "upload": return <Upload className="w-3.5 h-3.5 text-blue-600" />;
    case "processing_complete": return <CheckCircle2 className="w-3.5 h-3.5 text-green-600" />;
    case "processing_failed": return <AlertCircle className="w-3.5 h-3.5 text-red-500" />;
    case "download": return <ArrowUpRight className="w-3.5 h-3.5 text-slate-500" />;
    default: return <FileText className="w-3.5 h-3.5 text-slate-400" />;
  }
}

function ActivityLabel({ event }: { event: ActivityEvent }) {
  switch (event.type) {
    case "upload": return <>uploaded <span className="font-medium text-slate-800">{event.documentName}</span></>;
    case "processing_complete": return <><span className="font-medium text-slate-800">{event.documentName}</span> processed</>;
    case "processing_failed": return <><span className="font-medium text-slate-800">{event.documentName}</span> failed — {event.meta}</>;
    case "download": return <>downloaded <span className="font-medium text-slate-800">{event.documentName}</span></>;
    default: return <>{event.type}</>;
  }
}

export default function DashboardPage() {
  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-8 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Dashboard</h1>
          <p className="text-slate-500 text-sm mt-0.5">
            {mockTenant.name} — {new Date("2026-06-04").toLocaleDateString("en-MY", { weekday: "long", year: "numeric", month: "long", day: "numeric" })}
          </p>
        </div>
        <Link
          href="/upload"
          className="inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2.5 rounded-lg text-sm font-medium transition-colors"
        >
          <Upload className="w-4 h-4" />
          Upload Documents
        </Link>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <div className="stat-card">
          <div className="flex items-center justify-between mb-3">
            <span className="text-slate-500 text-sm">Total Documents</span>
            <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center">
              <FileText className="w-4 h-4 text-blue-600" />
            </div>
          </div>
          <p className="text-3xl font-bold text-slate-900">{mockTenant.documentsCount.toLocaleString()}</p>
          <p className="text-slate-400 text-xs mt-1 flex items-center gap-1">
            <TrendingUp className="w-3 h-3 text-green-500" />
            +23 this week
          </p>
        </div>

        <div className="stat-card">
          <div className="flex items-center justify-between mb-3">
            <span className="text-slate-500 text-sm">Processed</span>
            <div className="w-8 h-8 rounded-lg bg-green-50 flex items-center justify-center">
              <CheckCircle2 className="w-4 h-4 text-green-600" />
            </div>
          </div>
          <p className="text-3xl font-bold text-slate-900">{completed}</p>
          <p className="text-slate-400 text-xs mt-1">in this session</p>
        </div>

        <div className="stat-card">
          <div className="flex items-center justify-between mb-3">
            <span className="text-slate-500 text-sm">In Pipeline</span>
            <div className="w-8 h-8 rounded-lg bg-violet-50 flex items-center justify-center">
              <Clock className="w-4 h-4 text-violet-600" />
            </div>
          </div>
          <p className="text-3xl font-bold text-slate-900">{processing}</p>
          <p className="text-slate-400 text-xs mt-1">being processed now</p>
        </div>

        <div className="stat-card">
          <div className="flex items-center justify-between mb-3">
            <span className="text-slate-500 text-sm">Failed</span>
            <div className="w-8 h-8 rounded-lg bg-red-50 flex items-center justify-center">
              <AlertCircle className="w-4 h-4 text-red-500" />
            </div>
          </div>
          <p className="text-3xl font-bold text-slate-900">{failed}</p>
          <p className="text-slate-400 text-xs mt-1">need attention</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Recent documents table */}
        <div className="lg:col-span-2 bg-white border border-slate-200 rounded-xl overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
            <h2 className="font-semibold text-slate-900 text-sm">Recent Documents</h2>
            <Link href="/documents" className="text-blue-600 hover:text-blue-700 text-xs font-medium flex items-center gap-1">
              View all <ArrowUpRight className="w-3 h-3" />
            </Link>
          </div>
          <div className="divide-y divide-slate-50">
            {recentDocs.map((doc) => (
              <Link
                key={doc.id}
                href={`/documents/${doc.id}`}
                className="flex items-center gap-4 px-6 py-3.5 hover:bg-slate-50 transition-colors group"
              >
                <div className="w-8 h-8 rounded-lg bg-slate-100 flex items-center justify-center flex-shrink-0">
                  {doc.mimeType.startsWith("image/") ? (
                    <FileImage className="w-4 h-4 text-slate-500" />
                  ) : doc.hasTextLayer ? (
                    <FileText className="w-4 h-4 text-slate-500" />
                  ) : (
                    <FileScan className="w-4 h-4 text-slate-500" />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-slate-800 truncate group-hover:text-blue-700">
                    {doc.originalFilename}
                  </p>
                  <p className="text-xs text-slate-400">
                    {doc.uploadedBy} · {formatRelativeTime(doc.uploadedAt)}
                  </p>
                </div>
                <div className="flex items-center gap-3 flex-shrink-0">
                  <StatusBadge status={doc.status} />
                  <span className="text-xs text-slate-400">{formatBytes(doc.sizeBytes)}</span>
                </div>
              </Link>
            ))}
          </div>
        </div>

        {/* Right column */}
        <div className="space-y-6">
          {/* Storage card */}
          <div className="bg-white border border-slate-200 rounded-xl p-5">
            <h2 className="font-semibold text-slate-900 text-sm mb-4">Storage Usage</h2>
            <div className="flex items-end justify-between mb-2">
              <span className="text-2xl font-bold text-slate-900">{storagePercent}%</span>
              <span className="text-slate-400 text-xs">{formatBytes(mockTenant.storageLimitBytes)} limit</span>
            </div>
            <div className="h-2 bg-slate-100 rounded-full overflow-hidden mb-3">
              <div
                className={`h-full rounded-full ${storagePercent > 80 ? "bg-red-500" : storagePercent > 60 ? "bg-amber-500" : "bg-blue-500"}`}
                style={{ width: `${storagePercent}%` }}
              />
            </div>
            <p className="text-slate-500 text-xs">
              {formatBytes(mockTenant.storageUsedBytes)} used of {formatBytes(mockTenant.storageLimitBytes)}
            </p>

            <div className="mt-4 pt-4 border-t border-slate-100 grid grid-cols-2 gap-3 text-xs">
              <div>
                <p className="text-slate-400">PDFs</p>
                <p className="font-semibold text-slate-700 mt-0.5">1,089</p>
              </div>
              <div>
                <p className="text-slate-400">Images</p>
                <p className="font-semibold text-slate-700 mt-0.5">158</p>
              </div>
            </div>
          </div>

          {/* Activity feed */}
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-100">
              <h2 className="font-semibold text-slate-900 text-sm">Activity</h2>
            </div>
            <div className="divide-y divide-slate-50">
              {mockActivity.slice(0, 6).map((event) => (
                <div key={event.id} className="px-5 py-3 flex items-start gap-3">
                  <div className="w-6 h-6 rounded-full bg-slate-100 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <ActivityIcon type={event.type} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-slate-600">
                      <span className="font-medium text-slate-700">{event.userName}</span>{" "}
                      <ActivityLabel event={event} />
                    </p>
                    <p className="text-xs text-slate-400 mt-0.5">{formatRelativeTime(event.timestamp)}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
