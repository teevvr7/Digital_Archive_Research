"use client";

import { useEffect, useState } from "react";
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
  Tag as TagIcon,
  UserPlus,
} from "lucide-react";
import { StatusBadge } from "@/components/status-badge";
import { ActivityIcon, ActivityLabel } from "@/components/activity-item";
import { formatBytes, formatRelativeTime } from "@/lib/format";
import { apiDashboard, type DashboardResponse } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function DashboardPage() {
  const { tenant, user } = useAuth();
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    apiDashboard()
      .then(setData)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : String(e))
      );
  }, []);

  const stats = data?.stats;
  const recentDocs = data?.recentDocuments ?? [];
  const activity = data?.activity ?? [];

  const storagePercent = stats
    ? Math.min(100, Math.round((stats.storageUsedBytes / stats.storageLimitBytes) * 100))
    : 0;

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-8 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Dashboard</h1>
          <p className="text-slate-500 text-sm mt-0.5">
            {tenant?.name ?? "—"} —{" "}
            {new Date().toLocaleDateString("en-MY", {
              weekday: "long",
              year: "numeric",
              month: "long",
              day: "numeric",
            })}
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

      {error && (
        <div className="mb-6 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
          {error}
        </div>
      )}

      {/* First-run checklist — disappears on its own once totalDocuments > 0 */}
      {stats && stats.totalDocuments === 0 && (
        <div className="mb-8 bg-blue-50 border border-blue-200 rounded-xl p-5">
          <h2 className="font-semibold text-blue-900 text-sm mb-3">Get started</h2>
          <ul className="space-y-2.5">
            <li>
              <Link
                href="/upload"
                className="flex items-center gap-2.5 text-sm text-blue-800 hover:text-blue-900"
              >
                <Upload className="w-4 h-4 flex-shrink-0" />
                Upload your first document
              </Link>
            </li>
            <li>
              <Link
                href="/tags"
                className="flex items-center gap-2.5 text-sm text-blue-800 hover:text-blue-900"
              >
                <TagIcon className="w-4 h-4 flex-shrink-0" />
                Organize with tags — Paid, Unpaid, Important, and Needs Review are
                already set up for you
              </Link>
            </li>
            {user?.role === "admin" && (
              <li>
                <Link
                  href="/settings"
                  className="flex items-center gap-2.5 text-sm text-blue-800 hover:text-blue-900"
                >
                  <UserPlus className="w-4 h-4 flex-shrink-0" />
                  Invite your team from Settings &gt; Users &amp; Access
                </Link>
              </li>
            )}
          </ul>
        </div>
      )}

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <div className="stat-card">
          <div className="flex items-center justify-between mb-3">
            <span className="text-slate-500 text-sm">Total Documents</span>
            <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center">
              <FileText className="w-4 h-4 text-blue-600" />
            </div>
          </div>
          <p className="text-3xl font-bold text-slate-900">
            {(stats?.totalDocuments ?? 0).toLocaleString()}
          </p>
          <p className="text-slate-400 text-xs mt-1 flex items-center gap-1">
            <TrendingUp className="w-3 h-3 text-green-500" />
            real-time count
          </p>
        </div>

        <div className="stat-card">
          <div className="flex items-center justify-between mb-3">
            <span className="text-slate-500 text-sm">Processed</span>
            <div className="w-8 h-8 rounded-lg bg-green-50 flex items-center justify-center">
              <CheckCircle2 className="w-4 h-4 text-green-600" />
            </div>
          </div>
          <p className="text-3xl font-bold text-slate-900">{stats?.processed ?? 0}</p>
          <p className="text-slate-400 text-xs mt-1">extraction complete</p>
        </div>

        <div className="stat-card">
          <div className="flex items-center justify-between mb-3">
            <span className="text-slate-500 text-sm">In Pipeline</span>
            <div className="w-8 h-8 rounded-lg bg-violet-50 flex items-center justify-center">
              <Clock className="w-4 h-4 text-violet-600" />
            </div>
          </div>
          <p className="text-3xl font-bold text-slate-900">{stats?.inPipeline ?? 0}</p>
          <p className="text-slate-400 text-xs mt-1">queued for processing</p>
        </div>

        <div className="stat-card">
          <div className="flex items-center justify-between mb-3">
            <span className="text-slate-500 text-sm">Failed</span>
            <div className="w-8 h-8 rounded-lg bg-red-50 flex items-center justify-center">
              <AlertCircle className="w-4 h-4 text-red-500" />
            </div>
          </div>
          <p className="text-3xl font-bold text-slate-900">{stats?.failed ?? 0}</p>
          <p className="text-slate-400 text-xs mt-1">need attention</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Recent documents table */}
        <div className="lg:col-span-2 bg-white border border-slate-200 rounded-xl overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
            <h2 className="font-semibold text-slate-900 text-sm">Recent Documents</h2>
            <Link
              href="/documents"
              className="text-blue-600 hover:text-blue-700 text-xs font-medium flex items-center gap-1"
            >
              View all <ArrowUpRight className="w-3 h-3" />
            </Link>
          </div>
          <div className="divide-y divide-slate-50">
            {recentDocs.length === 0 ? (
              <p className="px-6 py-8 text-center text-slate-400 text-sm">
                No documents yet — upload your first file.
              </p>
            ) : (
              recentDocs.map((doc) => (
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
                      {doc.title || doc.originalFilename}
                    </p>
                    <p className="text-xs text-slate-400">
                      {doc.uploadedBy} · {formatRelativeTime(doc.uploadedAt)}
                    </p>
                  </div>
                  <div className="flex items-center gap-3 flex-shrink-0">
                    <StatusBadge status={doc.status} />
                    <span className="text-xs text-slate-400">
                      {formatBytes(doc.sizeBytes)}
                    </span>
                  </div>
                </Link>
              ))
            )}
          </div>
        </div>

        {/* Right column */}
        <div className="space-y-6">
          {/* Storage card */}
          <div className="bg-white border border-slate-200 rounded-xl p-5">
            <h2 className="font-semibold text-slate-900 text-sm mb-4">Storage Usage</h2>
            <div className="flex items-end justify-between mb-2">
              <span className="text-2xl font-bold text-slate-900">{storagePercent}%</span>
              <span className="text-slate-400 text-xs">
                {stats ? formatBytes(stats.storageLimitBytes) : "—"} limit
              </span>
            </div>
            <div className="h-2 bg-slate-100 rounded-full overflow-hidden mb-3">
              <div
                className={`h-full rounded-full ${
                  storagePercent > 80
                    ? "bg-red-500"
                    : storagePercent > 60
                    ? "bg-amber-500"
                    : "bg-blue-500"
                }`}
                style={{ width: `${storagePercent}%` }}
              />
            </div>
            <p className="text-slate-500 text-xs">
              {stats
                ? `${formatBytes(stats.storageUsedBytes)} used of ${formatBytes(stats.storageLimitBytes)}`
                : "—"}
            </p>
          </div>

          {/* Activity feed */}
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-100">
              <h2 className="font-semibold text-slate-900 text-sm">Activity</h2>
            </div>
            <div className="divide-y divide-slate-50">
              {activity.length === 0 ? (
                <p className="px-5 py-6 text-center text-slate-400 text-sm">
                  No activity yet.
                </p>
              ) : (
                activity.map((event) => (
                  <div key={event.id} className="px-5 py-3 flex items-start gap-3">
                    <div className="w-6 h-6 rounded-full bg-slate-100 flex items-center justify-center flex-shrink-0 mt-0.5">
                      <ActivityIcon type={event.type} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs text-slate-600">
                        <span className="font-medium text-slate-700">
                          {event.userName}
                        </span>{" "}
                        <ActivityLabel event={event} />
                      </p>
                      <p className="text-xs text-slate-400 mt-0.5">
                        {formatRelativeTime(event.timestamp)}
                      </p>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
