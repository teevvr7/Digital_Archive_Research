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
  Mail,
  AlertCircle,
  Cpu,
  Save,
  RefreshCw,
} from "lucide-react";
import { ActivityIcon, ActivityLabel } from "@/components/activity-item";
import { formatBytes, formatRelativeTime } from "@/lib/format";
import {
  apiUpdateTenant,
  apiDashboard,
  apiActivity,
  apiListUsers,
  apiInviteUser,
  apiUpdateUserRole,
  apiRemoveUser,
  apiListIDPConfigs,
  apiListTemplates,
  apiCreateTemplate,
  apiUpdateTemplate,
  apiSetDefaultTemplate,
  apiDeleteTemplate,
  apiCreateDocumentType,
  apiDeleteDocumentType,
  type DashboardResponse,
  type ActivityListResponse,
  type AuthUser,
  type IDPConfig,
  type Template,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { useConfirm } from "@/components/ui/confirm-dialog";

type Tab = "organisation" | "users" | "activity" | "security" | "api" | "notifications" | "idp";

const TABS: { id: Tab; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: "organisation", label: "Organisation", icon: Building2 },
  { id: "users", label: "Users & Access", icon: Users },
  { id: "activity", label: "Activity", icon: ActivityIconLucide },
  { id: "security", label: "Security", icon: Shield },
  { id: "api", label: "API Keys", icon: Key },
  { id: "idp", label: "IDP Control Center", icon: Cpu },
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
  const toast = useToast();
  const confirm = useConfirm();
  const [activeTab, setActiveTab] = useState<Tab>("organisation");

  const [orgName, setOrgName] = useState("");
  // Text, not number: empty string means "no override, use the default" —
  // distinct from "0", which isn't a valid retention window anyway.
  const [retentionDaysInput, setRetentionDaysInput] = useState("");
  const [orgSaving, setOrgSaving] = useState(false);
  const [orgSaved, setOrgSaved] = useState(false);
  const [orgError, setOrgError] = useState("");

  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [activityFeed, setActivityFeed] = useState<ActivityListResponse | null>(null);
  const [activityLoading, setActivityLoading] = useState(false);

  const isAdmin = user?.role === "admin";
  const [teamUsers, setTeamUsers] = useState<AuthUser[] | null>(null);
  const [teamLoading, setTeamLoading] = useState(false);
  const [teamError, setTeamError] = useState("");
  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteName, setInviteName] = useState("");
  const [inviteRole, setInviteRole] = useState<"user" | "admin">("user");
  const [inviteSubmitting, setInviteSubmitting] = useState(false);
  const [inviteError, setInviteError] = useState("");
  const [roleUpdatingId, setRoleUpdatingId] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);

  useEffect(() => {
    if (tenant) {
      setOrgName(tenant.name);
      setRetentionDaysInput(tenant.trashRetentionDays?.toString() ?? "");
    }
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

  const loadTeam = () => {
    setTeamLoading(true);
    apiListUsers()
      .then(setTeamUsers)
      .catch((e) => setTeamError(e instanceof Error ? e.message : "Failed to load users."))
      .finally(() => setTeamLoading(false));
  };

  useEffect(() => {
    if (activeTab !== "users") return;
    setTeamError("");
    loadTeam();
  }, [activeTab]);

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inviteEmail.trim() || !inviteName.trim()) return;
    setInviteError("");
    setInviteSubmitting(true);
    try {
      await apiInviteUser(inviteEmail.trim(), inviteName.trim(), inviteRole);
      setInviteOpen(false);
      setInviteEmail("");
      setInviteName("");
      setInviteRole("user");
      loadTeam();
      toast.success(`Invite sent to ${inviteEmail.trim()}.`);
    } catch (e) {
      setInviteError(e instanceof Error ? e.message : "Failed to send invite.");
    } finally {
      setInviteSubmitting(false);
    }
  };

  const handleRoleChange = async (targetId: string, role: string) => {
    setRoleUpdatingId(targetId);
    try {
      await apiUpdateUserRole(targetId, role);
      loadTeam();
      toast.success("Role updated.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to change role.");
    } finally {
      setRoleUpdatingId(null);
    }
  };

  const handleRemoveUser = async (row: AuthUser) => {
    const ok = await confirm({
      title: "Remove user?",
      body: `Remove ${row.name} (${row.email}) from your organisation? This cannot be undone.`,
      confirmLabel: "Remove",
      danger: true,
    });
    if (!ok) return;
    setRemovingId(row.id);
    try {
      await apiRemoveUser(row.id);
      loadTeam();
      toast.success(`${row.name} removed from your organisation.`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to remove user.");
    } finally {
      setRemovingId(null);
    }
  };

  const handleSaveOrg = async () => {
    if (!orgName.trim()) return;
    const trimmedRetention = retentionDaysInput.trim();
    const retentionDays = trimmedRetention === "" ? null : Number(trimmedRetention);
    if (retentionDays !== null && (!Number.isInteger(retentionDays) || retentionDays < 1)) {
      setOrgError("Trash retention must be a whole number of days (1 or more), or blank.");
      return;
    }
    setOrgSaving(true);
    setOrgError("");
    try {
      await apiUpdateTenant(orgName.trim(), retentionDays);
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
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1.5">
                      Trash retention (days)
                    </label>
                    <input
                      type="number"
                      min={1}
                      value={retentionDaysInput}
                      onChange={(e) => setRetentionDaysInput(e.target.value)}
                      placeholder={`Default: ${tenant?.effectiveTrashRetentionDays ?? 30}`}
                      className="w-full px-3.5 py-2.5 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-900"
                    />
                    <p className="text-xs text-slate-400 mt-1">
                      Documents in the trash longer than this are permanently deleted
                      automatically. Leave blank to use the default.
                    </p>
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
                  <p className="text-slate-400 text-xs mt-0.5">
                    {teamUsers ? `${teamUsers.length} member${teamUsers.length === 1 ? "" : "s"}` : "…"}
                  </p>
                </div>
                <button
                  onClick={() => isAdmin && setInviteOpen(true)}
                  disabled={!isAdmin}
                  title={isAdmin ? undefined : "Admin access required"}
                  className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                    isAdmin
                      ? "bg-blue-600 hover:bg-blue-700 text-white"
                      : "bg-slate-100 text-slate-400 cursor-not-allowed"
                  }`}
                >
                  <Plus className="w-4 h-4" />
                  Invite user
                </button>
              </div>
              {teamError && (
                <p className="px-6 py-3 text-sm text-red-600 bg-red-50 border-b border-red-100">
                  {teamError}
                </p>
              )}
              <div className="px-6 divide-y divide-slate-50">
                {!teamUsers ? (
                  <p className="py-8 text-center text-slate-400 text-sm">
                    {teamLoading ? "Loading…" : "No members found."}
                  </p>
                ) : (
                  teamUsers.map((row) => {
                    const isSelf = row.id === user?.id;
                    const pending = row.lastLoginAt === null;
                    return (
                      <div key={row.id} className="flex items-center gap-4 py-3.5">
                        <div className="w-9 h-9 rounded-full bg-blue-100 flex items-center justify-center flex-shrink-0">
                          <span className="text-blue-700 text-sm font-semibold">
                            {row.avatarInitials}
                          </span>
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <p className="text-sm font-medium text-slate-800">{row.name}</p>
                            {isSelf && (
                              <span className="px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded text-xs font-medium">
                                You
                              </span>
                            )}
                            {pending && (
                              <span className="px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded text-xs font-medium">
                                Invite pending
                              </span>
                            )}
                          </div>
                          <p className="text-xs text-slate-400">{row.email}</p>
                        </div>
                        {isAdmin && !isSelf ? (
                          <select
                            value={row.role}
                            disabled={roleUpdatingId === row.id}
                            onChange={(e) => handleRoleChange(row.id, e.target.value)}
                            className="text-xs rounded-lg border border-slate-200 px-2.5 py-1.5 bg-white text-slate-600 capitalize focus:outline-none focus:ring-2 focus:ring-blue-500"
                          >
                            <option value="user">User</option>
                            <option value="admin">Admin</option>
                          </select>
                        ) : (
                          <span className="text-xs rounded-lg border border-slate-200 px-2.5 py-1.5 bg-slate-50 text-slate-600 capitalize">
                            {row.role}
                          </span>
                        )}
                        {isAdmin && !isSelf && (
                          <button
                            onClick={() => handleRemoveUser(row)}
                            disabled={removingId === row.id}
                            title="Remove from organisation"
                            className="text-slate-300 hover:text-red-600 disabled:opacity-50 transition-colors"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        )}
                      </div>
                    );
                  })
                )}
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

          {/* IDP Control Center */}
          {activeTab === "idp" && (
            <IDPControlCenter />
          )}
        </div>
      </div>

      <Modal open={inviteOpen} onClose={() => setInviteOpen(false)} title="Invite a teammate">
            <form onSubmit={handleInvite} className="space-y-4">
              <div>
                <label className="text-xs text-slate-500 block mb-1">Name *</label>
                <input
                  value={inviteName}
                  onChange={(e) => setInviteName(e.target.value)}
                  placeholder="Jane Doe"
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="text-xs text-slate-500 block mb-1">Email *</label>
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="jane@company.com"
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="text-xs text-slate-500 block mb-1">Role</label>
                <select
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value as "user" | "admin")}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="user">User</option>
                  <option value="admin">Admin</option>
                </select>
              </div>

              {inviteError && (
                <div className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                  {inviteError}
                </div>
              )}

              <div className="flex items-center gap-2 pt-1">
                <button
                  type="submit"
                  disabled={inviteSubmitting || !inviteEmail.trim() || !inviteName.trim()}
                  className="flex-1 flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white py-2.5 rounded-lg text-sm font-medium transition-colors"
                >
                  {inviteSubmitting ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Mail className="w-4 h-4" />
                  )}
                  {inviteSubmitting ? "Sending…" : "Send invite"}
                </button>
                <button
                  type="button"
                  onClick={() => setInviteOpen(false)}
                  className="px-4 py-2.5 border border-slate-200 text-slate-600 rounded-lg text-sm font-medium hover:bg-slate-50 transition-colors"
                >
                  Cancel
                </button>
              </div>
            </form>
      </Modal>
    </div>
  );
}

function IDPControlCenter() {
  const [configs, setConfigs] = useState<IDPConfig[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedConfigId, setSelectedConfigId] = useState<string | null>(null);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);

  // Form fields
  const [templateName, setTemplateName] = useState("");
  const [method, setMethod] = useState("default");
  const [useImage, setUseImage] = useState(false);
  const [useOcr, setUseOcr] = useState(true);
  const [schemaStr, setSchemaStr] = useState("");
  const [instruction, setInstruction] = useState("");
  const [rules, setRules] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Custom document type modal fields
  const [showNewTypeModal, setShowNewTypeModal] = useState(false);
  const [newTypeName, setNewTypeName] = useState("");
  const [newTypeDesc, setNewTypeDesc] = useState("");

  const fetchConfigsAndTemplates = async () => {
    setLoading(true);
    setError(null);
    try {
      const [configRes, templateRes] = await Promise.all([
        apiListIDPConfigs(),
        apiListTemplates(),
      ]);
      setConfigs(configRes.configs);
      setTemplates(templateRes);

      if (configRes.configs.length > 0) {
        const firstConfig = configRes.configs[0];
        setSelectedConfigId(firstConfig.documentTypeId);

        // Find default template or any template for this config
        const configTemplates = templateRes.filter(
          (t) => t.documentTypeId === firstConfig.documentTypeId
        );
        if (configTemplates.length > 0) {
          const defaultTpl = configTemplates.find((t) => t.isDefault) || configTemplates[0];
          setSelectedTemplateId(defaultTpl.id);
          setTemplateName(defaultTpl.name);
          setMethod(defaultTpl.extractionMethod);
          setUseImage(defaultTpl.useImage);
          setUseOcr(defaultTpl.useOcr);
          setSchemaStr(defaultTpl.jsonSchema ? JSON.stringify(defaultTpl.jsonSchema, null, 2) : "{}");
          setInstruction(defaultTpl.instruction || "");
          setRules(defaultTpl.rules || "");
        } else {
          // If no templates exist yet, reset to default layout creation
          setSelectedTemplateId("new");
          setTemplateName(`Default ${firstConfig.name} Layout`);
          setMethod(firstConfig.extractionMethod);
          setUseImage(false);
          setUseOcr(true);
          setSchemaStr(firstConfig.jsonSchema ? JSON.stringify(firstConfig.jsonSchema, null, 2) : "{}");
          setInstruction(firstConfig.instruction || "");
          setRules(firstConfig.rules || "");
        }
      }
    } catch (err: unknown) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Failed to load IDP configurations.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConfigsAndTemplates();
  }, []);

  const handleSelectDocType = (cfg: IDPConfig) => {
    setSelectedConfigId(cfg.documentTypeId);
    const configTemplates = templates.filter((t) => t.documentTypeId === cfg.documentTypeId);
    if (configTemplates.length > 0) {
      const defaultTpl = configTemplates.find((t) => t.isDefault) || configTemplates[0];
      handleSelectTemplate(defaultTpl);
    } else {
      setSelectedTemplateId("new");
      setTemplateName(`Default ${cfg.name} Layout`);
      setMethod(cfg.extractionMethod);
      setUseImage(false);
      setUseOcr(true);
      setSchemaStr(cfg.jsonSchema ? JSON.stringify(cfg.jsonSchema, null, 2) : "{}");
      setInstruction(cfg.instruction || "");
      setRules(cfg.rules || "");
    }
    setSaveSuccess(false);
  };

  const handleSelectTemplate = (tpl: Template) => {
    setSelectedTemplateId(tpl.id);
    setTemplateName(tpl.name);
    setMethod(tpl.extractionMethod);
    setUseImage(tpl.useImage);
    setUseOcr(tpl.useOcr);
    setSchemaStr(tpl.jsonSchema ? JSON.stringify(tpl.jsonSchema, null, 2) : "{}");
    setInstruction(tpl.instruction || "");
    setRules(tpl.rules || "");
    setSaveSuccess(false);
  };

  const handleSave = async () => {
    if (!selectedConfigId) return;

    if (!useImage && !useOcr) {
      setError("Please select at least one input modality (Image or OCR).");
      return;
    }

    setSaving(true);
    setError(null);
    setSaveSuccess(false);

    try {
      let parsedSchema = {};
      if (schemaStr.trim()) {
        try {
          parsedSchema = JSON.parse(schemaStr);
        } catch {
          throw new Error("Invalid JSON in Target JSON Schema field");
        }
      }

      if (selectedTemplateId === "new") {
        const created = await apiCreateTemplate({
          documentTypeId: selectedConfigId,
          name: templateName.trim() || "New Layout",
          extractionMethod: method,
          jsonSchema: parsedSchema,
          instruction: instruction.trim() || null,
          rules: rules.trim() || null,
          useImage,
          useOcr,
        });
        setTemplates((prev) => [...prev, created]);
        setSelectedTemplateId(created.id);
      } else if (selectedTemplateId) {
        const updated = await apiUpdateTemplate(selectedTemplateId, {
          name: templateName.trim() || "Layout Template",
          extractionMethod: method,
          jsonSchema: parsedSchema,
          instruction: instruction.trim() || null,
          rules: rules.trim() || null,
          useImage,
          useOcr,
        });
        setTemplates((prev) => prev.map((t) => (t.id === selectedTemplateId ? updated : t)));
      }

      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err: unknown) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Failed to update configuration.");
    } finally {
      setSaving(false);
    }
  };

  const handleSetDefault = async () => {
    if (!selectedTemplateId || selectedTemplateId === "new") return;
    setSaving(true);
    setError(null);
    try {
      const updated = await apiSetDefaultTemplate(selectedTemplateId);
      setTemplates((prev) =>
        prev.map((t) => {
          if (t.documentTypeId === updated.documentTypeId) {
            return { ...t, isDefault: t.id === updated.id };
          }
          return t;
        })
      );
    } catch (err: unknown) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Failed to set default template.");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedTemplateId || selectedTemplateId === "new") return;
    if (!confirm("Are you sure you want to delete this layout template?")) return;
    setSaving(true);
    setError(null);
    try {
      await apiDeleteTemplate(selectedTemplateId);
      const remaining = templates.filter((t) => t.id !== selectedTemplateId);
      setTemplates(remaining);

      // Select another template for the active config if available
      const configTemplates = remaining.filter((t) => t.documentTypeId === selectedConfigId);
      if (configTemplates.length > 0) {
        const defaultTpl = configTemplates.find((t) => t.isDefault) || configTemplates[0];
        handleSelectTemplate(defaultTpl);
      } else {
        setSelectedTemplateId("new");
        setTemplateName(`Default Layout`);
        setUseImage(false);
        setUseOcr(true);
      }
    } catch (err: unknown) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Failed to delete template.");
    } finally {
      setSaving(false);
    }
  };

  const handleCreateDocType = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTypeName.trim()) return;
    
    setSaving(true);
    setError(null);
    try {
      const created = await apiCreateDocumentType({
        name: newTypeName.trim(),
        description: newTypeDesc.trim() || null,
        extractionMethod: "paddle_qwen"
      });
      
      setConfigs((prev) => [...prev, created]);
      setSelectedConfigId(created.documentTypeId);
      
      // Select the newly created document type for default layout creation
      setSelectedTemplateId("new");
      setTemplateName(`Default Layout`);
      setMethod("paddle_qwen");
      setUseImage(false);
      setUseOcr(true);
      setSchemaStr(created.jsonSchema ? JSON.stringify(created.jsonSchema, null, 2) : "{}");
      setInstruction(created.instruction || "");
      setRules(created.rules || "");
      
      // Reset form & close modal
      setNewTypeName("");
      setNewTypeDesc("");
      setShowNewTypeModal(false);
    } catch (err: unknown) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Failed to create document type.");
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteDocType = async () => {
    if (!selectedConfigId || !activeConfig) return;
    if (activeConfig.isSystem) return;
    
    if (
      !confirm(
        `Are you sure you want to delete the document type "${activeConfig.name}"? This will permanently delete all associated templates and layouts.`
      )
    ) {
      return;
    }
    
    setSaving(true);
    setError(null);
    try {
      await apiDeleteDocumentType(selectedConfigId);
      
      const remainingConfigs = configs.filter((c) => c.documentTypeId !== selectedConfigId);
      setConfigs(remainingConfigs);
      
      // Clean up templates associated with it
      const remainingTemplates = templates.filter((t) => t.documentTypeId !== selectedConfigId);
      setTemplates(remainingTemplates);
      
      if (remainingConfigs.length > 0) {
        const firstConfig = remainingConfigs[0];
        handleSelectDocType(firstConfig);
      } else {
        setSelectedConfigId(null);
        setSelectedTemplateId(null);
      }
    } catch (err: unknown) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Failed to delete document type.");
    } finally {
      setSaving(false);
    }
  };

  const activeConfig = configs.find((c) => c.documentTypeId === selectedConfigId);
  const activeTemplate = templates.find((t) => t.id === selectedTemplateId);

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12">
        <RefreshCw className="w-8 h-8 text-blue-500 animate-spin mr-3" />
        <span className="text-slate-500 text-sm">Loading configurations...</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="bg-white border border-slate-200 rounded-xl p-6">
        <div className="flex items-start gap-4">
          <div className="w-10 h-10 rounded-lg bg-blue-50 flex items-center justify-center flex-shrink-0">
            <Cpu className="w-5 h-5 text-blue-600" />
          </div>
          <div>
            <h2 className="font-semibold text-slate-900 text-lg">IDP Core Routing & Models</h2>
            <p className="text-slate-500 text-sm mt-0.5">
              Dynamically configure extraction templates, input modalities, layouts, and system instructions. Settings are isolated per tenant.
            </p>
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 flex gap-3 text-sm text-red-800">
          <AlertCircle className="w-4 h-4 text-red-600 flex-shrink-0 mt-0.5" />
          <p>{error}</p>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Document Type & Layout Selector */}
        <div className="bg-white border border-slate-200 rounded-xl p-4 space-y-4 h-fit">
          <div className="flex items-center justify-between px-2">
            <div>
              <h3 className="font-semibold text-slate-800 text-sm">Document Types</h3>
              <p className="text-slate-400 text-[11px] mt-0.5">Select category to configure</p>
            </div>
            <button
              onClick={() => setShowNewTypeModal(true)}
              className="p-1.5 border border-slate-200 hover:bg-slate-50 text-blue-600 rounded-lg cursor-pointer"
              title="Add Custom Document Type"
            >
              <Plus className="w-4 h-4" />
            </button>
          </div>
          <div className="space-y-2">
            {configs.map((cfg) => {
              const isSelected = cfg.documentTypeId === selectedConfigId;
              const configTemplates = templates.filter((t) => t.documentTypeId === cfg.documentTypeId);

              return (
                <div key={cfg.documentTypeId} className="space-y-1">
                  <button
                    onClick={() => handleSelectDocType(cfg)}
                    className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-sm text-left transition-colors font-semibold cursor-pointer ${
                      isSelected
                        ? "bg-slate-100 text-slate-900"
                        : "text-slate-600 hover:bg-slate-50"
                    }`}
                  >
                    <div className="flex flex-col items-start">
                      <span className="capitalize">{cfg.name}</span>
                      {cfg.isSystem ? (
                        <span className="px-1 py-0.2 bg-slate-100 text-slate-400 text-[8px] rounded uppercase font-bold tracking-wider mt-0.5">
                          System
                        </span>
                      ) : (
                        <span className="px-1 py-0.2 bg-emerald-50 text-emerald-600 text-[8px] rounded uppercase font-bold tracking-wider mt-0.5">
                          Custom
                        </span>
                      )}
                    </div>
                    <span className="px-1.5 py-0.5 bg-slate-200 text-slate-700 text-[10px] rounded font-medium">
                      {configTemplates.length}
                    </span>
                  </button>

                  {isSelected && (
                    <div className="pl-4 pr-1 py-1 space-y-1 border-l-2 border-slate-200 ml-3">
                      {configTemplates.map((tpl) => {
                        const isTplSelected = tpl.id === selectedTemplateId;
                        return (
                          <button
                            key={tpl.id}
                            onClick={() => handleSelectTemplate(tpl)}
                            className={`w-full flex items-center justify-between px-2.5 py-2 rounded-md text-xs text-left transition-colors cursor-pointer ${
                              isTplSelected
                                ? "bg-blue-50 text-blue-700 font-semibold"
                                : "text-slate-500 hover:bg-slate-50"
                            }`}
                          >
                            <span className="truncate max-w-[120px]">{tpl.name}</span>
                            {tpl.isDefault && (
                              <span className="px-1.5 py-0.2 bg-blue-100 text-blue-800 text-[8px] rounded font-bold uppercase flex-shrink-0">
                                Default
                              </span>
                            )}
                          </button>
                        );
                      })}

                      <button
                        onClick={() => {
                          setSelectedTemplateId("new");
                          setTemplateName(`Custom ${cfg.name} Layout`);
                          setMethod("paddle_qwen");
                          setUseImage(false);
                          setUseOcr(true);
                          setSchemaStr(cfg.jsonSchema ? JSON.stringify(cfg.jsonSchema, null, 2) : "{}");
                          setInstruction(cfg.instruction || "");
                          setRules(cfg.rules || "");
                          setSaveSuccess(false);
                        }}
                        className="w-full flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs text-blue-600 hover:bg-blue-50 text-left transition-colors font-medium cursor-pointer mt-1"
                      >
                        <Plus className="w-3.5 h-3.5" />
                        Add layout template
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Configuration Panel */}
        {activeConfig && (
          <div className="md:col-span-2 bg-white border border-slate-200 rounded-xl p-6 space-y-6">
            <div className="flex justify-between items-start gap-4">
              <div>
                <h3 className="font-semibold text-slate-900 font-sans">
                  {selectedTemplateId === "new" ? "Create New Extraction Layout" : `Configure "${templateName}" Layout Settings`}
                </h3>
                <p className="text-slate-400 text-xs mt-0.5 font-sans">
                  Set model targets, multimodal options, and layout key properties.
                </p>
              </div>
              {!activeConfig.isSystem && (
                <button
                  onClick={handleDeleteDocType}
                  disabled={saving}
                  className="px-2.5 py-1.5 bg-red-50 hover:bg-red-100 text-red-600 rounded-lg text-xs font-semibold cursor-pointer border border-red-200 transition-colors flex items-center gap-1.5"
                  title="Delete Custom Document Type Category"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  Delete Category
                </button>
              )}
            </div>

            {/* Layout Name Input */}
            <div className="space-y-2">
              <label className="block text-sm font-semibold text-slate-700">
                Template Layout Name
              </label>
              <input
                type="text"
                value={templateName}
                onChange={(e) => setTemplateName(e.target.value)}
                className="w-full text-sm p-3 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-800 bg-slate-50/50 font-medium"
                placeholder="e.g. Acme Corp Specific Layout"
              />
            </div>

            {/* Model Toggle */}
            <div className="space-y-2">
              <label className="block text-sm font-semibold text-slate-700">
                Extraction Pipeline Strategy
              </label>
              <div className="grid grid-cols-2 gap-4">
                <button
                  onClick={() => setMethod("default")}
                  className={`p-4 border rounded-xl text-left transition-all cursor-pointer ${
                    method === "default"
                      ? "border-blue-500 bg-blue-50/50 shadow-sm"
                      : "border-slate-200 hover:border-slate-300 bg-white"
                  }`}
                >
                  <p className={`text-sm font-semibold ${method === "default" ? "text-blue-700" : "text-slate-800"}`}>
                    Teammate VLM Cascade
                  </p>
                  <p className="text-xs text-slate-400 mt-1 font-sans">
                    Uses default vLLM endpoint with multi-page token compression.
                  </p>
                </button>
                <button
                  onClick={() => setMethod("paddle_qwen")}
                  className={`p-4 border rounded-xl text-left transition-all cursor-pointer ${
                    method === "paddle_qwen"
                      ? "border-blue-500 bg-blue-50/50 shadow-sm"
                      : "border-slate-200 hover:border-slate-300 bg-white"
                  }`}
                >
                  <p className={`text-sm font-semibold ${method === "paddle_qwen" ? "text-blue-700" : "text-slate-800"}`}>
                    PaddleOCR-VL + Qwen-VL
                  </p>
                  <p className="text-xs text-slate-400 mt-1 font-sans">
                    First extracts via PaddleOCR (exact text & layouts), then reasons via Qwen-VL with math validation.
                  </p>
                </button>
              </div>
            </div>

            {/* Input Modalities */}
            <div className="space-y-2">
              <label className="block text-sm font-semibold text-slate-700">
                Input Modalities sent to GPU Server
              </label>
              <p className="text-slate-400 text-xs mt-0.5 font-sans">
                Select which inputs are dispatched to the AI server. At least one must be checked.
              </p>
              <div className="grid grid-cols-2 gap-4 mt-2">
                <button
                  type="button"
                  onClick={() => setUseOcr((v) => !v)}
                  className={`p-4 border rounded-xl text-left transition-all cursor-pointer flex justify-between items-center ${
                    useOcr
                      ? "border-blue-500 bg-blue-50/50 shadow-sm"
                      : "border-slate-200 hover:border-slate-300 bg-white"
                  }`}
                >
                  <div>
                    <p className={`text-sm font-semibold ${useOcr ? "text-blue-700" : "text-slate-800"}`}>
                      OCR Text Content
                    </p>
                    <p className="text-xs text-slate-400 mt-0.5 font-sans">
                      Sends precise character stream & structural layout bounding boxes.
                    </p>
                  </div>
                  <div className={`relative w-8 h-4 rounded-full transition-colors flex-shrink-0 ${useOcr ? "bg-blue-600" : "bg-slate-200"}`}>
                    <span className={`absolute top-0.5 w-3 h-3 rounded-full bg-white shadow transition-transform ${useOcr ? "translate-x-4.5" : "translate-x-0.5"}`} />
                  </div>
                </button>

                <button
                  type="button"
                  onClick={() => setUseImage((v) => !v)}
                  className={`p-4 border rounded-xl text-left transition-all cursor-pointer flex justify-between items-center ${
                    useImage
                      ? "border-blue-500 bg-blue-50/50 shadow-sm"
                      : "border-slate-200 hover:border-slate-300 bg-white"
                  }`}
                >
                  <div>
                    <p className={`text-sm font-semibold ${useImage ? "text-blue-700" : "text-slate-800"}`}>
                      Raw Image Modality
                    </p>
                    <p className="text-xs text-slate-400 mt-0.5 font-sans">
                      Sends the document page image directly for visual layout parsing.
                    </p>
                  </div>
                  <div className={`relative w-8 h-4 rounded-full transition-colors flex-shrink-0 ${useImage ? "bg-blue-600" : "bg-slate-200"}`}>
                    <span className={`absolute top-0.5 w-3 h-3 rounded-full bg-white shadow transition-transform ${useImage ? "translate-x-4.5" : "translate-x-0.5"}`} />
                  </div>
                </button>
              </div>
            </div>

            {/* Instruction Editor */}
            <div className="space-y-2">
              <div className="flex justify-between items-center">
                <label className="block text-sm font-semibold text-slate-700">
                  System Instruction (Plain Text)
                </label>
                <span className="text-slate-400 text-[10px]">Main instruction guiding the model</span>
              </div>
              <textarea
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                rows={4}
                placeholder="You are a precise data extraction assistant..."
                className="w-full text-sm p-3 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-800 bg-slate-50/50 font-mono"
              />
            </div>

            {/* Rules Editor */}
            <div className="space-y-2">
              <div className="flex justify-between items-center">
                <label className="block text-sm font-semibold text-slate-700">
                  System Rules & Extraction Constraints (Plain Text)
                </label>
                <span className="text-slate-400 text-[10px]">Rules for formatting, nesting, and values</span>
              </div>
              <textarea
                value={rules}
                onChange={(e) => setRules(e.target.value)}
                rows={6}
                placeholder="RULES:&#10;1. DATES: All dates MUST be YYYY-MM-DD..."
                className="w-full text-sm p-3 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-800 bg-slate-50/50 font-mono"
              />
            </div>

            {/* Target JSON Schema Editor */}
            <div className="space-y-2">
              <div className="flex justify-between items-center">
                <label className="block text-sm font-semibold text-slate-700">
                  Target JSON Schema (Structured JSON)
                </label>
                <span className="text-slate-400 text-[10px]">Must be valid JSON object</span>
              </div>
              <textarea
                value={schemaStr}
                onChange={(e) => setSchemaStr(e.target.value)}
                rows={8}
                placeholder="{}"
                className="w-full font-mono text-xs p-3 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-800 bg-slate-50/50"
              />
            </div>

            <div className="flex justify-between items-center pt-4 border-t border-slate-100">
              <div className="flex gap-2">
                {selectedTemplateId !== "new" && activeTemplate && !activeTemplate.isDefault && (
                  <button
                    onClick={handleSetDefault}
                    disabled={saving}
                    className="px-3 py-2 border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold cursor-pointer font-sans"
                  >
                    Set as Default
                  </button>
                )}
                {selectedTemplateId !== "new" && (
                  <button
                    onClick={handleDelete}
                    disabled={saving}
                    className="px-3 py-2 border border-red-200 text-red-600 hover:bg-red-50 rounded-lg text-xs font-semibold cursor-pointer flex items-center gap-1 font-sans"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    Delete Layout
                  </button>
                )}
              </div>
              <div className="flex items-center gap-3">
                {saveSuccess && (
                  <span className="flex items-center gap-1 text-xs text-green-600 font-semibold font-sans">
                    <Check className="w-3.5 h-3.5" /> Layout saved successfully
                  </span>
                )}
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="flex items-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-lg text-sm font-semibold transition-colors cursor-pointer font-sans"
                >
                  {saving ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin" /> Saving...
                    </>
                  ) : (
                    <>
                      <Save className="w-4 h-4" />
                      {selectedTemplateId === "new" ? "Create Layout" : "Save Configuration"}
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Create Custom Document Type Modal */}
      {showNewTypeModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-sm">
          <div className="bg-white rounded-xl shadow-lg border border-slate-200 p-6 max-w-md w-full mx-4">
            <h3 className="text-lg font-semibold text-slate-900 mb-2 font-sans">Create Custom Document Type</h3>
            <p className="text-slate-400 text-xs mb-5 font-sans">Add a new category of documents for classification and extraction routing.</p>
            <form onSubmit={handleCreateDocType} className="space-y-4">
              <div>
                <label className="block text-sm font-semibold text-slate-700 mb-1 font-sans">Name</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Purchase Order, Contract"
                  value={newTypeName}
                  onChange={(e) => setNewTypeName(e.target.value)}
                  className="w-full text-sm p-3 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-800 font-sans"
                />
              </div>
              <div>
                <label className="block text-sm font-semibold text-slate-700 mb-1 font-sans">Description (Optional)</label>
                <textarea
                  placeholder="Describe the document category purpose..."
                  value={newTypeDesc}
                  onChange={(e) => setNewTypeDesc(e.target.value)}
                  rows={3}
                  className="w-full text-sm p-3 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-800 font-sans"
                />
              </div>
              <div className="flex justify-end gap-3 pt-3 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setShowNewTypeModal(false)}
                  className="px-4 py-2 border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-lg text-sm font-semibold cursor-pointer font-sans"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-semibold cursor-pointer disabled:opacity-50 font-sans"
                >
                  Create
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
