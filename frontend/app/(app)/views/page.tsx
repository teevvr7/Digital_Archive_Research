"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Bookmark,
  Plus,
  Pencil,
  Trash2,
  X,
  Save,
  Loader2,
  ExternalLink,
} from "lucide-react";
import {
  apiSavedViews,
  apiCreateSavedView,
  apiPatchSavedView,
  apiDeleteSavedView,
  type SavedViewCreateInput,
} from "@/lib/api";
import { useConfirm } from "@/components/ui/confirm-dialog";
import type { SavedView } from "@/types";

function filterStateLabel(state: Record<string, unknown>): string {
  const parts: string[] = [];
  if (state.status) parts.push(`Status: ${state.status}`);
  if (state.type) parts.push(`Type: ${state.type}`);
  if (state.q) parts.push(`Search: "${state.q}"`);
  if (state.inbox) parts.push("Inbox only");
  if (state.dateFrom || state.dateTo) {
    parts.push(`Date: ${state.dateFrom ?? "…"} → ${state.dateTo ?? "…"}`);
  }
  return parts.length > 0 ? parts.join(" · ") : "No filters";
}

function viewToQueryString(state: Record<string, unknown>): string {
  const params = new URLSearchParams();
  const map: Record<string, string> = {
    status: "status",
    type: "type",
    tag_id: "tag_id",
    correspondent_id: "correspondent_id",
    date_from: "date_from",
    date_to: "date_to",
    q: "q",
    sort: "sort",
    inbox: "inbox",
  };
  for (const [key, param] of Object.entries(map)) {
    const val = state[key];
    if (val !== undefined && val !== null && val !== "" && val !== "all" && val !== false) {
      params.set(param, String(val));
    }
  }
  const qs = params.toString();
  return qs ? `/documents?${qs}` : "/documents";
}

const EMPTY_FORM: SavedViewCreateInput = { name: "", filterState: {}, isDefault: false };

export default function SavedViewsPage() {
  const confirm = useConfirm();
  const [views, setViews] = useState<SavedView[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<SavedViewCreateInput>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");

  useEffect(() => {
    apiSavedViews()
      .then(setViews)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  const openCreate = () => {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setFormError("");
    setShowForm(true);
  };

  const openEdit = (view: SavedView) => {
    setEditingId(view.id);
    setForm({ name: view.name, filterState: view.filterState, isDefault: view.isDefault });
    setFormError("");
    setShowForm(true);
  };

  const closeForm = () => {
    setShowForm(false);
    setEditingId(null);
    setForm(EMPTY_FORM);
    setFormError("");
  };

  const handleSave = async () => {
    if (!form.name.trim()) {
      setFormError("Name is required.");
      return;
    }
    setSaving(true);
    setFormError("");
    try {
      if (editingId) {
        const updated = await apiPatchSavedView(editingId, { name: form.name, isDefault: form.isDefault });
        setViews((prev) => prev.map((v) => (v.id === editingId ? updated : v)));
      } else {
        const created = await apiCreateSavedView(form);
        setViews((prev) => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)));
      }
      closeForm();
    } catch (e: unknown) {
      setFormError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    const ok = await confirm({
      title: "Delete saved view?",
      body: "Delete this saved view?",
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    try {
      await apiDeleteSavedView(id);
      setViews((prev) => prev.filter((v) => v.id !== id));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  };

  return (
    <div className="p-8 max-w-3xl">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Bookmark className="w-5 h-5 text-slate-500" />
          <div>
            <h1 className="text-xl font-semibold text-slate-800">Saved Views</h1>
            <p className="text-sm text-slate-500 mt-0.5">
              Save filter combinations to quickly return to common document sets.
            </p>
          </div>
        </div>
        <button
          onClick={openCreate}
          className="flex items-center gap-2 px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg transition-colors"
        >
          <Plus className="w-4 h-4" /> New view
        </button>
      </div>

      {error && <p className="text-red-500 text-sm mb-4">{error}</p>}

      {showForm && (
        <div className="mb-6 bg-white border border-slate-200 rounded-xl p-5 shadow-sm space-y-4">
          <h2 className="text-sm font-semibold text-slate-700">
            {editingId ? "Edit view" : "New saved view"}
          </h2>
          <div>
            <label className="text-xs text-slate-500 block mb-1">Name *</label>
            <input
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="e.g. Pending Invoices"
              className="w-full px-3 py-1.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <label className="flex items-center gap-2 cursor-pointer text-sm text-slate-700">
            <input
              type="checkbox"
              checked={form.isDefault ?? false}
              onChange={(e) => setForm((f) => ({ ...f, isDefault: e.target.checked }))}
              className="rounded border-slate-300"
            />
            Set as default view
          </label>
          {formError && <p className="text-red-500 text-xs">{formError}</p>}
          <div className="flex gap-2 pt-1">
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-1.5 px-4 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm rounded-lg"
            >
              {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
              Save
            </button>
            <button
              onClick={closeForm}
              disabled={saving}
              className="flex items-center gap-1.5 px-4 py-1.5 border border-slate-200 hover:bg-slate-50 text-slate-600 text-sm rounded-lg"
            >
              <X className="w-3.5 h-3.5" /> Cancel
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-slate-400 text-sm">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading…
        </div>
      ) : views.length === 0 ? (
        <div className="text-center py-16 text-slate-400">
          <Bookmark className="w-8 h-8 mx-auto mb-3 opacity-40" />
          <p className="text-sm">No saved views yet.</p>
          <p className="text-xs mt-1">
            Go to{" "}
            <Link href="/documents" className="text-blue-600 hover:underline">
              Documents
            </Link>{" "}
            and use the filter bar, then save the current view.
          </p>
        </div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50">
                <th className="text-left px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wide">Name</th>
                <th className="text-left px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wide">Filters</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {views.map((view) => (
                <tr key={view.id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-slate-800">{view.name}</span>
                      {view.isDefault && (
                        <span className="px-1.5 py-0.5 bg-blue-100 text-blue-700 text-xs rounded font-medium">
                          Default
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-slate-500 text-xs">
                    {filterStateLabel(view.filterState)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1 justify-end">
                      <Link
                        href={viewToQueryString(view.filterState)}
                        className="p-1.5 rounded hover:bg-blue-50 text-slate-400 hover:text-blue-600"
                        title="Open view"
                      >
                        <ExternalLink className="w-3.5 h-3.5" />
                      </Link>
                      <button
                        onClick={() => openEdit(view)}
                        className="p-1.5 rounded hover:bg-slate-100 text-slate-400 hover:text-slate-600"
                        title="Edit"
                      >
                        <Pencil className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => handleDelete(view.id)}
                        className="p-1.5 rounded hover:bg-red-50 text-slate-400 hover:text-red-600"
                        title="Delete"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
