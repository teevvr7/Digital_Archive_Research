"use client";

import { useEffect, useState } from "react";
import { Plus, Pencil, Trash2, Loader2, X, Check, Users } from "lucide-react";
import {
  apiCorrespondents,
  apiCreateCorrespondent,
  apiPatchCorrespondent,
  apiDeleteCorrespondent,
  type CorrespondentCreateInput,
} from "@/lib/api";
import type { Correspondent } from "@/types";

const ALGORITHMS = [
  { value: "any", label: "Any word" },
  { value: "all", label: "All words" },
  { value: "literal", label: "Literal substring" },
  { value: "regex", label: "Regular expression" },
  { value: "none", label: "None (manual only)" },
];

type FormState = {
  name: string;
  match: string;
  matchingAlgorithm: string;
  isInsensitive: boolean;
};

const emptyForm = (): FormState => ({
  name: "",
  match: "",
  matchingAlgorithm: "any",
  isInsensitive: true,
});

export default function CorrespondentsPage() {
  const [correspondents, setCorrespondents] = useState<Correspondent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [showForm, setShowForm] = useState(false);
  const [editingItem, setEditingItem] = useState<Correspondent | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm());
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    apiCorrespondents()
      .then(setCorrespondents)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const openCreate = () => {
    setEditingItem(null);
    setForm(emptyForm());
    setFormError("");
    setShowForm(true);
  };

  const openEdit = (item: Correspondent) => {
    setEditingItem(item);
    setForm({
      name: item.name,
      match: item.match,
      matchingAlgorithm: item.matchingAlgorithm,
      isInsensitive: item.isInsensitive,
    });
    setFormError("");
    setShowForm(true);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) { setFormError("Name is required."); return; }
    setSaving(true);
    setFormError("");
    try {
      const data: CorrespondentCreateInput = {
        name: form.name.trim(),
        match: form.match,
        matchingAlgorithm: form.matchingAlgorithm,
        isInsensitive: form.isInsensitive,
      };
      if (editingItem) {
        await apiPatchCorrespondent(editingItem.id, data);
      } else {
        await apiCreateCorrespondent(data);
      }
      setShowForm(false);
      load();
    } catch (e: unknown) {
      setFormError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (item: Correspondent) => {
    if (!confirm(`Delete correspondent "${item.name}"? Documents linked to it will be unlinked.`)) return;
    setDeletingId(item.id);
    try {
      await apiDeleteCorrespondent(item.id);
      load();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="p-8 max-w-4xl">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 flex items-center gap-2">
            <Users className="w-6 h-6 text-slate-400" />
            Correspondents
          </h1>
          <p className="text-slate-500 text-sm mt-0.5">
            Track senders and vendors. Correspondents can auto-link to documents via match rules.
          </p>
        </div>
        <button
          onClick={openCreate}
          className="inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2.5 rounded-lg text-sm font-medium transition-colors"
        >
          <Plus className="w-4 h-4" /> New correspondent
        </button>
      </div>

      {error && (
        <div className="mb-4 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3">{error}</div>
      )}

      {/* Form modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold text-slate-800">
                {editingItem ? "Edit correspondent" : "New correspondent"}
              </h2>
              <button onClick={() => setShowForm(false)} className="text-slate-400 hover:text-slate-600">
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="text-xs text-slate-500 block mb-1">Name *</label>
                <input
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="e.g. Tenaga Nasional Berhad"
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="text-xs text-slate-500 block mb-1">Auto-match pattern</label>
                <input
                  value={form.match}
                  onChange={(e) => setForm((f) => ({ ...f, match: e.target.value }))}
                  placeholder="e.g. tenaga tnb (space-separated for any/all)"
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="text-xs text-slate-500 block mb-1">Matching algorithm</label>
                <select
                  value={form.matchingAlgorithm}
                  onChange={(e) => setForm((f) => ({ ...f, matchingAlgorithm: e.target.value }))}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                >
                  {ALGORITHMS.map((a) => (
                    <option key={a.value} value={a.value}>{a.label}</option>
                  ))}
                </select>
              </div>

              <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.isInsensitive}
                  onChange={(e) => setForm((f) => ({ ...f, isInsensitive: e.target.checked }))}
                  className="rounded"
                />
                Case-insensitive matching
              </label>

              {formError && <p className="text-xs text-red-600">{formError}</p>}

              <div className="flex gap-2 pt-2">
                <button
                  type="submit"
                  disabled={saving}
                  className="flex-1 flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
                >
                  {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                  {editingItem ? "Save changes" : "Create correspondent"}
                </button>
                <button
                  type="button"
                  onClick={() => setShowForm(false)}
                  className="px-4 py-2 border border-slate-200 text-slate-600 hover:bg-slate-50 rounded-lg text-sm transition-colors"
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* List */}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-5 h-5 animate-spin text-slate-400" />
          </div>
        ) : correspondents.length === 0 ? (
          <div className="py-16 text-center">
            <Users className="w-10 h-10 text-slate-200 mx-auto mb-3" />
            <p className="text-slate-400 text-sm">
              No correspondents yet. Create one to start linking senders to documents.
            </p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50">
                <th className="text-left px-6 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Name</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Match pattern</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Algorithm</th>
                <th className="px-6 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {correspondents.map((item) => (
                <tr key={item.id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-6 py-3.5 font-medium text-slate-800">{item.name}</td>
                  <td className="px-4 py-3.5 text-slate-500 text-xs font-mono">
                    {item.match || <span className="text-slate-300 italic">—</span>}
                  </td>
                  <td className="px-4 py-3.5 text-slate-500 text-xs capitalize">
                    {ALGORITHMS.find((a) => a.value === item.matchingAlgorithm)?.label ?? item.matchingAlgorithm}
                  </td>
                  <td className="px-6 py-3.5">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        onClick={() => openEdit(item)}
                        className="p-1.5 rounded-md hover:bg-slate-100 text-slate-400 hover:text-slate-700 transition-colors"
                        title="Edit"
                      >
                        <Pencil className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => handleDelete(item)}
                        disabled={deletingId === item.id}
                        className="p-1.5 rounded-md hover:bg-red-50 text-slate-400 hover:text-red-500 transition-colors disabled:opacity-50"
                        title="Delete"
                      >
                        {deletingId === item.id ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <Trash2 className="w-3.5 h-3.5" />
                        )}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
