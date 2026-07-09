"use client";

import { useEffect, useState } from "react";
import {
  Building2,
  Users,
  Key,
  Shield,
  Bell,
  Activity as ActivityIconLucide,
  Trash2,
  Plus,
  Check,
  Loader2,
  Clock,
} from "lucide-react";
import { ActivityIcon, ActivityLabel } from "@/components/activity-item";
import { formatBytes, formatRelativeTime } from "@/lib/format";
import { apiUpdateTenant, apiDashboard, apiActivity, type DashboardResponse, type ActivityListResponse } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Tab = "organisation" | "users" | "activity" | "security" | "api" | "notifications";

const TABS: { id: Tab; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: "organisation", label: "Organisation", icon: Building2 },
  { id: "users", label: "Users & Access", icon: Users },
  { id: "activity", label: "Activity", icon: ActivityIconLucide },
  { id: "security", label: "Security", icon: Shield },
  { id: "api", label: "API Keys", icon: Key },
  { id: "notifications", label: "Notifications", icon: Bell },
];

const FAMILY_LABELS: Record<string, string> = {
  pdf: "PDFs",
  image: "Images",
  office: "Office files",
  text: "Text/CSV",
  email: "Emails",
  other: "Other",
};

/** A static "not built yet" panel — used instead of interactive controls that
 * don't persist anywhere. Faking security/notification toggles in a document
 * archive is a trust liability, so we say plainly what's not live yet. */
function ComingSoonPanel({
  title,
  description,
  items,
}: {
  title: string;
  description: string;
  items: string[];
}) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-6">
      <h2 className="font-semibold text-slate-900 mb-1.5">{title}</h2>
      <p className="text-slate-500 text-sm mb-5">{description}</p>
      <ul className="space-y-2.5">
        {items.map((item) => (
          <li key={item} className="flex items-center gap-2.5 text-sm text-slate-500">
            <span className="w-1.5 h-1.5 rounded-full bg-slate-300 flex-shrink-0" />
            {item}
            <span className="ml-auto text-xs text-slate-400 font-medium">Coming soon</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function SettingsPage() {
  const { user, tenant, refresh } = useAuth();
  const [activeTab, setActiveTab] = useState<Tab>("organisation");

  const [orgName, setOrgName] = useState("");
  const [orgSaving, setOrgSaving] = useState(false);
  const [orgSaved, setOrgSaved] = useState(false);
  const [orgError, setOrgError] = useState("");

  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [activityFeed, setActivityFeed] = useState<ActivityListResponse | null>(null);
  const [activityLoading, setActivityLoading] = useState(false);

  useEffect(() => {
    if (tenant) setOrgName(tenant.name);
  }, [tenant]);

  useEffect(() => {
    apiDashboard().then(setDashboard).catch(() => {});
  }, []);

  // Fetch page 1 fresh every time the Activity tab is opened — a plain page-state
  // effect would instead re-fetch whatever page was last loaded and append it a
  // second time (duplicating rows) if the user had already clicked "Load more".
  useEffect(() => {
    if (activeTab !== "activity") return;
    setActivityFeed(null);
    setActivityLoading(true);
    apiActivity({ page: 1 })
      .then(setActivityFeed)
      .catch(() => {})
      .finally(() => setActivityLoading(false));
  }, [activeTab]);

  const loadMoreActivity = () => {
    if (!activityFeed || activityLoading) return;
    setActivityLoading(true);
    apiActivity({ page: activityFeed.page + 1 })
      .then((res) => {
        setActivityFeed((prev) =>
          prev ? { ...res, items: [...prev.items, ...res.items] } : res
        );
      })
      .catch(() => {})
      .finally(() => setActivityLoading(false));
  };

  const handleSaveOrg = async () => {
    if (!orgName.trim()) return;
    setOrgSaving(true);
    setOrgError("");
    try {
      await apiUpdateTenant(orgName.trim());
      await refresh();
      setOrgSaved(true);
      setTimeout(() => setOrgSaved(false), 2500);
    } catch (e) {
      setOrgError(e instanceof Error ? e.message : "Failed to save. Please try again.");
    } finally {
      setOrgSaving(false);
    }
  };

  const storagePercent = tenant
    ? Math.min(100, Math.round((tenant.storageUsedBytes / tenant.storageLimitBytes) * 100))
    : 0;
  const byFamily = dashboard?.stats.documentsByFamily ?? {};
  const familyEntries = Object.entries(byFamily).filter(([, count]) => count > 0);
  const hasMoreActivity = activityFeed
    ? activityFeed.page * activityFeed.pageSize < activityFeed.total
    : false;

  return (
    <div className="p-8 max-w-5xl">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-slate-900">Settings</h1>
        <p className="text-slate-500 text-sm mt-0.5">Manage your organisation, users, and activity.</p>
      </div>

      <div className="flex gap-8">
        {/* Sidebar nav */}
        <aside className="w-52 flex-shrink-0">
          <nav className="space-y-0.5">
            {TABS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                onClick={() => setActiveTab(id)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-left transition-colors ${
                  activeTab === id
                    ? "bg-blue-50 text-blue-700"
                    : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                <Icon className="w-4 h-4 flex-shrink-0" />
                {label}
              </button>
            ))}
          </nav>
        </aside>

        {/* Content */}
        <div className="flex-1 min-w-0">
          {/* Organisation */}
          {activeTab === "organisation" && (
            <div className="space-y-6">
              <div className="bg-white border border-slate-200 rounded-xl p-6">
                <h2 className="font-semibold text-slate-900 mb-5">Organisation Details</h2>
                <div className="space-y-4 max-w-md">
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1.5">
                      Organisation name
                    </label>
                    <input
                      value={orgName}
                      onChange={(e) => setOrgName(e.target.value)}
                      className="w-full px-3.5 py-2.5 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-900"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1.5">
                      Tenant ID
                    </label>
                    <input
                      value={tenant?.id ?? ""}
                      disabled
                      className="w-full px-3.5 py-2.5 rounded-lg border border-slate-100 text-sm bg-slate-50 text-slate-400 font-mono"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1.5">
                      Plan
                    </label>
                    <span className="inline-block px-3 py-1.5 bg-blue-100 text-blue-700 rounded-lg text-sm font-semibold capitalize">
                      {tenant?.plan ?? "—"}
                    </span>
                  </div>
                  {orgError && <p className="text-sm text-red-600">{orgError}</p>}
                  <button
                    onClick={handleSaveOrg}
                    disabled={orgSaving || !orgName.trim()}
                    className="flex items-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
                  >
                    {orgSaving ? (
                      <><Loader2 className="w-4 h-4 animate-spin" /> Saving…</>
                    ) : orgSaved ? (
                      <><Check className="w-4 h-4" /> Saved!</>
                    ) : (
                      "Save changes"
                    )}
                  </button>
                </div>
              </div>

              {/* Storage */}
              <div className="bg-white border border-slate-200 rounded-xl p-6">
                <h2 className="font-semibold text-slate-900 mb-5">Storage</h2>
                <div className="flex items-end justify-between mb-2">
                  <span className="text-3xl font-bold text-slate-900">{storagePercent}%</span>
                  <span className="text-slate-400 text-sm">
                    {tenant ? formatBytes(tenant.storageLimitBytes) : "—"} limit
                  </span>
                </div>
                <div className="h-2.5 bg-slate-100 rounded-full overflow-hidden mb-3">
                  <div
                    className="h-full bg-blue-500 rounded-full"
                    style={{ width: `${storagePercent}%` }}
                  />
                </div>
                <p className="text-slate-500 text-sm">
                  {tenant ? formatBytes(tenant.storageUsedBytes) : "—"} used of{" "}
                  {tenant ? formatBytes(tenant.storageLimitBytes) : "—"}
                </p>

                {familyEntries.length > 0 && (
                  <div className="mt-4 pt-4 border-t border-slate-100 grid grid-cols-3 gap-4 text-sm">
                    {familyEntries.map(([family, count]) => (
                      <div key={family}>
                        <p className="text-slate-400 text-xs mb-0.5">
                          {FAMILY_LABELS[family] ?? family}
                        </p>
                        <p className="font-semibold text-slate-800">{count.toLocaleString()}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* PDPA */}
              <div className="bg-green-50 border border-green-200 rounded-xl p-5">
                <div className="flex items-start gap-3">
                  <Shield className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="font-semibold text-green-800 mb-1">PDPA Compliance</p>
                    <p className="text-green-700 text-sm">
                      Your data is isolated per-organisation at the database level (row-level
                      security) and processed in accordance with PDPA 2010. Documents are
                      encrypted in transit and at rest by the storage provider.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Users */}
          {activeTab === "users" && (
            <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
              <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
                <div>
                  <h2 className="font-semibold text-slate-900">Users & Access</h2>
                  <p className="text-slate-400 text-xs mt-0.5">1 member</p>
                </div>
                <button
                  disabled
                  title="Team accounts are coming in a future update"
                  className="flex items-center gap-1.5 px-3 py-2 bg-slate-100 text-slate-400 rounded-lg text-sm font-medium cursor-not-allowed"
                >
                  <Plus className="w-4 h-4" />
                  Invite user
                </button>
              </div>
              <div className="px-6 divide-y divide-slate-50">
                {user && (
                  <div className="flex items-center gap-4 py-3.5">
                    <div className="w-9 h-9 rounded-full bg-blue-100 flex items-center justify-center flex-shrink-0">
                      <span className="text-blue-700 text-sm font-semibold">
                        {user.avatarInitials}
                      </span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium text-slate-800">{user.name}</p>
                        <span className="px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded text-xs font-medium">
                          You
                        </span>
                      </div>
                      <p className="text-xs text-slate-400">{user.email}</p>
                    </div>
                    <span className="text-xs rounded-lg border border-slate-200 px-2.5 py-1.5 bg-slate-50 text-slate-600 capitalize">
                      {user.role}
                    </span>
                  </div>
                )}
              </div>
              <div className="px-6 py-3 bg-slate-50 border-t border-slate-100">
                <p className="text-xs text-slate-500">
                  Inviting teammates with admin/member roles is on the roadmap — for now each
                  organisation has a single account.
                </p>
              </div>
            </div>
          )}

          {/* Activity — real org-wide audit trail */}
          {activeTab === "activity" && (
            <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
              <div className="px-6 py-4 border-b border-slate-100">
                <h2 className="font-semibold text-slate-900">Activity</h2>
                <p className="text-slate-400 text-xs mt-0.5">
                  Every upload, edit, and deletion across your organisation.
                </p>
              </div>
              <div className="divide-y divide-slate-50">
                {!activityFeed || activityFeed.items.length === 0 ? (
                  <p className="px-6 py-8 text-center text-slate-400 text-sm">
                    {activityLoading ? "Loading…" : "No activity yet."}
                  </p>
                ) : (
                  activityFeed.items.map((event) => (
                    <div key={event.id} className="flex items-start gap-3 px-6 py-3">
                      <div className="mt-0.5">
                        <ActivityIcon type={event.type} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-slate-700">
                          <span className="font-medium text-slate-800">{event.userName}</span>{" "}
                          <ActivityLabel event={event} />
                        </p>
                        <p className="text-xs text-slate-400 flex items-center gap-1 mt-0.5">
                          <Clock className="w-3 h-3" />
                          {formatRelativeTime(event.timestamp)}
                        </p>
                      </div>
                    </div>
                  ))
                )}
              </div>
              {hasMoreActivity && (
                <div className="px-6 py-3 border-t border-slate-100 text-center">
                  <button
                    onClick={loadMoreActivity}
                    disabled={activityLoading}
                    className="text-sm text-blue-600 hover:text-blue-700 font-medium disabled:opacity-50"
                  >
                    {activityLoading ? "Loading…" : "Load more"}
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Security */}
          {activeTab === "security" && (
            <div className="space-y-4">
              <ComingSoonPanel
                title="Security"
                description="Access controls beyond the current single-account model."
                items={[
                  "Two-factor authentication",
                  "Configurable session timeout",
                  "IP allowlisting",
                ]}
              />
              <div className="bg-white border border-slate-200 rounded-xl p-6">
                <h2 className="font-semibold text-slate-900 mb-2">Danger Zone</h2>
                <p className="text-slate-500 text-sm mb-4">
                  Deleting an organisation is irreversible. Contact support to request this.
                </p>
                <button
                  disabled
                  title="Contact support to delete your organisation"
                  className="flex items-center gap-2 px-4 py-2.5 border border-red-100 text-red-300 rounded-lg text-sm font-medium cursor-not-allowed"
                >
                  <Trash2 className="w-4 h-4" />
                  Delete organisation
                </button>
              </div>
            </div>
          )}

          {/* API Keys */}
          {activeTab === "api" && (
            <ComingSoonPanel
              title="API Keys"
              description="Programmatic access for integrations, beyond the web app."
              items={["Create and revoke API keys", "Per-key scoped permissions"]}
            />
          )}

          {/* Notifications */}
          {activeTab === "notifications" && (
            <ComingSoonPanel
              title="Notifications"
              description="Email and in-app alerts for processing and account events."
              items={[
                "Processing complete / failed alerts",
                "Storage warning threshold",
                "Weekly activity digest",
              ]}
            />
          )}
        </div>
      </div>
    </div>
  );
}
