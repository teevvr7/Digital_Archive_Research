"use client";

import { useEffect, useState } from "react";
import { Plus, Pencil, Trash2, Loader2, X, Check, Tag as TagIcon, Wand2 } from "lucide-react";
import {
  apiTags,
  apiCreateTag,
  apiPatchTag,
  apiDeleteTag,
  apiApplyRules,
  type TagCreateInput,
} from "@/lib/api";
import type { Tag } from "@/types";

const PRESET_COLORS = [
  "#3B82F6", // blue
  "#10B981", // green
  "#F59E0B", // amber
  "#EF4444", // red
  "#8B5CF6", // violet
  "#EC4899", // pink
  "#06B6D4", // cyan
  "#6B7280", // gray
];

const ALGORITHMS = [
  { value: "any", label: "Any word" },
  { value: "all", label: "All words" },
  { value: "literal", label: "Literal substring" },
  { value: "regex", label: "Regular expression" },
  { value: "none", label: "None (manual only)" },
];

type FormState = {
  name: string;
  color: string;
  match: string;
  matchingAlgorithm: string;
  isInsensitive: boolean;
  isInboxTag: boolean;
};

const emptyForm = (): FormState => ({
  name: "",
  color: "#3B82F6",
  match: "",
  matchingAlgorithm: "any",
  isInsensitive: true,
  isInboxTag: false,
});

export default function TagsPage() {
  const [tags, setTags] = useState<Tag[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [showForm, setShowForm] = useState(false);
  const [editingTag, setEditingTag] = useState<Tag | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm());
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [applyingRules, setApplyingRules] = useState(false);

  const load = () => {
    setLoading(true);
    apiTags()
      .then(setTags)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const openCreate = () => {
    setEditingTag(null);
    setForm(emptyForm());
    setFormError("");
    setShowForm(true);
  };

  const openEdit = (tag: Tag) => {
    setEditingTag(tag);
    setForm({
      name: tag.name,
      color: tag.color,
      match: tag.match,
      matchingAlgorithm: tag.matchingAlgorithm,
      isInsensitive: tag.isInsensitive,
      isInboxTag: tag.isInboxTag,
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
      const data: TagCreateInput = {
        name: form.name.trim(),
        color: form.color,
        match: form.match,
        matchingAlgorithm: form.matchingAlgorithm,
        isInsensitive: form.isInsensitive,
        isInboxTag: form.isInboxTag,
      };
      if (editingTag) {
        await apiPatchTag(editingTag.id, data);
      } else {
        await apiCreateTag(data);
      }
      setShowForm(false);
      load();
    } catch (e: unknown) {
      setFormError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleApplyRules = async () => {
    if (
      !confirm(
        "Re-check every existing document against your current tag and correspondent rules? New matches will be applied — nothing already tagged is removed."
      )
    )
      return;
    setApplyingRules(true);
    try {
      let page = 1;
      let processed = 0;
      let hasMore = true;
      while (hasMore) {
        const res = await apiApplyRules(page);
        processed += res.processed;
        hasMore = res.hasMore;
        page += 1;
      }
      alert(`Done — checked ${processed} document${processed !== 1 ? "s" : ""} against your rules.`);
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Failed to apply rules");
    } finally {
      setApplyingRules(false);
    }
  };

  const handleDelete = async (tag: Tag) => {
    if (!confirm(`Delete tag "${tag.name}"? This will remove it from all documents.`)) return;
    setDeletingId(tag.id);
    try {
      await apiDeleteTag(tag.id);
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
            <TagIcon className="w-6 h-6 text-slate-400" />
            Tags
          </h1>
          <p className="text-slate-500 text-sm mt-0.5">
            Organize documents with colored labels. Tags can auto-assign via match rules.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleApplyRules}
            disabled={applyingRules}
            title="Re-check existing documents against your current match rules"
            className="inline-flex items-center gap-2 border border-slate-200 hover:bg-slate-50 text-slate-700 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
          >
            {applyingRules ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}
            Apply rules to existing documents
          </button>
          <button
            onClick={openCreate}
            className="inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2.5 rounded-lg text-sm font-medium transition-colors"
          >
            <Plus className="w-4 h-4" /> New tag
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3">{error}</div>
      )}

      {/* Form modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold text-slate-800">{editingTag ? "Edit tag" : "New tag"}</h2>
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
                  placeholder="e.g. Invoices"
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="text-xs text-slate-500 block mb-2">Color</label>
                <div className="flex items-center gap-2 flex-wrap">
                  {PRESET_COLORS.map((c) => (
                    <button
                      key={c}
                      type="button"
                      onClick={() => setForm((f) => ({ ...f, color: c }))}
                      className="w-6 h-6 rounded-full border-2 transition-transform hover:scale-110"
                      style={{
                        background: c,
                        borderColor: form.color === c ? "#1e40af" : "transparent",
                      }}
                    />
                  ))}
                  <input
                    type="color"
                    value={form.color}
                    onChange={(e) => setForm((f) => ({ ...f, color: e.target.value }))}
                    className="w-6 h-6 rounded cursor-pointer border border-slate-200"
                    title="Custom color"
                  />
                </div>
              </div>

              <div>
                <label className="text-xs text-slate-500 block mb-1">Auto-match pattern</label>
                <input
                  value={form.match}
                  onChange={(e) => setForm((f) => ({ ...f, match: e.target.value }))}
                  placeholder="e.g. invoice bill (space-separated for any/all)"
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

              <div className="flex items-center gap-4">
                <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={form.isInsensitive}
                    onChange={(e) => setForm((f) => ({ ...f, isInsensitive: e.target.checked }))}
                    className="rounded"
                  />
                  Case-insensitive
                </label>
                <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={form.isInboxTag}
                    onChange={(e) => setForm((f) => ({ ...f, isInboxTag: e.target.checked }))}
                    className="rounded"
                  />
                  Inbox tag
                </label>
              </div>

              {formError && <p className="text-xs text-red-600">{formError}</p>}

              <div className="flex gap-2 pt-2">
                <button
                  type="submit"
                  disabled={saving}
                  className="flex-1 flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
                >
                  {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                  {editingTag ? "Save changes" : "Create tag"}
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

      {/* Tag list */}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-5 h-5 animate-spin text-slate-400" />
          </div>
        ) : tags.length === 0 ? (
          <div className="py-16 text-center">
            <TagIcon className="w-10 h-10 text-slate-200 mx-auto mb-3" />
            <p className="text-slate-400 text-sm">No tags yet. Create your first tag to get started.</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50">
                <th className="text-left px-6 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Tag</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Match pattern</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Algorithm</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Inbox</th>
                <th className="px-6 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {tags.map((tag) => (
                <tr key={tag.id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-6 py-3.5">
                    <div className="flex items-center gap-2">
                      <span
                        className="w-3 h-3 rounded-full flex-shrink-0"
                        style={{ background: tag.color }}
                      />
                      <span
                        className="px-2 py-0.5 rounded text-xs font-medium"
                        style={{ background: tag.color + "22", color: tag.color }}
                      >
                        {tag.name}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3.5 text-slate-500 text-xs font-mono">
                    {tag.match || <span className="text-slate-300 italic">—</span>}
                  </td>
                  <td className="px-4 py-3.5 text-slate-500 text-xs capitalize">
                    {ALGORITHMS.find((a) => a.value === tag.matchingAlgorithm)?.label ?? tag.matchingAlgorithm}
                  </td>
                  <td className="px-4 py-3.5 text-xs">
                    {tag.isInboxTag ? (
                      <span className="px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-xs">Inbox</span>
                    ) : (
                      <span className="text-slate-300">—</span>
                    )}
                  </td>
                  <td className="px-6 py-3.5">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        onClick={() => openEdit(tag)}
                        className="p-1.5 rounded-md hover:bg-slate-100 text-slate-400 hover:text-slate-700 transition-colors"
                        title="Edit"
                      >
                        <Pencil className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => handleDelete(tag)}
                        disabled={deletingId === tag.id}
                        className="p-1.5 rounded-md hover:bg-red-50 text-slate-400 hover:text-red-500 transition-colors disabled:opacity-50"
                        title="Delete"
                      >
                        {deletingId === tag.id ? (
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
