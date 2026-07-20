"use client";

import { useEffect, useState } from "react";
import { Plus, Pencil, Trash2, X, Save, Loader2, SlidersHorizontal } from "lucide-react";
import {
  apiCustomFields,
  apiCreateCustomField,
  apiPatchCustomField,
  apiDeleteCustomField,
  apiPredefinedFields,
  apiAddPredefinedField,
  apiPatchPredefinedField,
  apiRemovePredefinedField,
  type CustomFieldCreateInput,
} from "@/lib/api";
import { useConfirm } from "@/components/ui/confirm-dialog";
import type { CustomField, PredefinedField } from "@/types";

const FIELD_TYPES = [
  { value: "text", label: "Text" },
  { value: "number", label: "Number" },
  { value: "date", label: "Date" },
  { value: "boolean", label: "Yes / No" },
  { value: "select", label: "Select (dropdown)" },
];

// Same fixed 7-value set used by the upload page and document detail page.
const DOC_TYPES = [
  { value: "invoice", label: "Invoice" },
  { value: "receipt", label: "Receipt" },
  { value: "contract", label: "Contract" },
  { value: "report", label: "Report" },
  { value: "letter", label: "Letter" },
  { value: "form", label: "Form" },
  { value: "other", label: "Other" },
];

const EMPTY_FORM: CustomFieldCreateInput = {
  name: "",
  fieldType: "text",
  options: [],
  position: 0,
};

export default function CustomFieldsPage() {
  const confirm = useConfirm();
  const [fields, setFields] = useState<CustomField[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<CustomFieldCreateInput>(EMPTY_FORM);
  const [optionInput, setOptionInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");

  // Predefined-fields-by-type state
  const [predefined, setPredefined] = useState<Record<string, PredefinedField[]>>({});
  const [addingForType, setAddingForType] = useState<string | null>(null);
  const [selectedFieldToAdd, setSelectedFieldToAdd] = useState("");
  const [addRequired, setAddRequired] = useState(false);
  const [predefinedError, setPredefinedError] = useState("");

  useEffect(() => {
    apiCustomFields()
      .then(setFields)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
    apiPredefinedFields().then(setPredefined).catch(() => {});
  }, []);

  const openCreate = () => {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setOptionInput("");
    setFormError("");
    setShowForm(true);
  };

  const openEdit = (field: CustomField) => {
    setEditingId(field.id);
    setForm({
      name: field.name,
      fieldType: field.fieldType,
      options: field.options,
      position: field.position,
    });
    setOptionInput("");
    setFormError("");
    setShowForm(true);
  };

  const closeForm = () => {
    setShowForm(false);
    setEditingId(null);
    setForm(EMPTY_FORM);
    setFormError("");
  };

  const addOption = () => {
    const opt = optionInput.trim();
    if (!opt || form.options?.includes(opt)) return;
    setForm((f) => ({ ...f, options: [...(f.options ?? []), opt] }));
    setOptionInput("");
  };

  const removeOption = (opt: string) =>
    setForm((f) => ({ ...f, options: (f.options ?? []).filter((o) => o !== opt) }));

  const handleSave = async () => {
    if (!form.name.trim()) {
      setFormError("Name is required.");
      return;
    }
    if (form.fieldType === "select" && (form.options ?? []).length === 0) {
      setFormError("Select fields need at least one option.");
      return;
    }
    setSaving(true);
    setFormError("");
    try {
      if (editingId) {
        const updated = await apiPatchCustomField(editingId, {
          name: form.name,
          options: form.options,
          position: form.position,
        });
        setFields((prev) => prev.map((f) => (f.id === editingId ? updated : f)));
      } else {
        const created = await apiCreateCustomField(form);
        setFields((prev) => [...prev, created].sort((a, b) => a.position - b.position || a.name.localeCompare(b.name)));
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
      title: "Delete custom field?",
      body: "Delete this custom field? All values set on documents will also be removed.",
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    try {
      await apiDeleteCustomField(id);
      setFields((prev) => prev.filter((f) => f.id !== id));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  };

  const openAddPredefined = (docType: string) => {
    setAddingForType(docType);
    setSelectedFieldToAdd("");
    setAddRequired(false);
    setPredefinedError("");
  };

  const handleAddPredefined = async (docType: string) => {
    if (!selectedFieldToAdd) return;
    setPredefinedError("");
    try {
      const created = await apiAddPredefinedField(docType, {
        fieldId: selectedFieldToAdd,
        required: addRequired,
      });
      setPredefined((prev) => ({
        ...prev,
        [docType]: [...(prev[docType] ?? []), created],
      }));
      setAddingForType(null);
    } catch (e: unknown) {
      setPredefinedError(e instanceof Error ? e.message : "Could not attach field");
    }
  };

  const handleTogglePredefinedRequired = async (
    docType: string,
    field: PredefinedField,
  ) => {
    try {
      const updated = await apiPatchPredefinedField(docType, field.fieldId, {
        required: !field.required,
      });
      setPredefined((prev) => ({
        ...prev,
        [docType]: (prev[docType] ?? []).map((f) => (f.fieldId === field.fieldId ? updated : f)),
      }));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not update field");
    }
  };

  const handleRemovePredefined = async (docType: string, fieldId: string) => {
    try {
      await apiRemovePredefinedField(docType, fieldId);
      setPredefined((prev) => ({
        ...prev,
        [docType]: (prev[docType] ?? []).filter((f) => f.fieldId !== fieldId),
      }));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not remove field");
    }
  };

  return (
    <div className="p-8 max-w-3xl">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <SlidersHorizontal className="w-5 h-5 text-slate-500" />
          <div>
            <h1 className="text-xl font-semibold text-slate-800">Custom Fields</h1>
            <p className="text-sm text-slate-500 mt-0.5">
              Define additional typed fields that can be set on any document.
            </p>
          </div>
        </div>
        <button
          onClick={openCreate}
          className="flex items-center gap-2 px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg transition-colors"
        >
          <Plus className="w-4 h-4" /> New field
        </button>
      </div>

      {error && <p className="text-red-500 text-sm mb-4">{error}</p>}

      {/* Field form */}
      {showForm && (
        <div className="mb-6 bg-white border border-slate-200 rounded-xl p-5 shadow-sm space-y-4">
          <h2 className="text-sm font-semibold text-slate-700">
            {editingId ? "Edit field" : "New field"}
          </h2>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-slate-500 block mb-1">Name *</label>
              <input
                data-testid="new-field-name"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="e.g. Project Code"
                className="w-full px-3 py-1.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="text-xs text-slate-500 block mb-1">Type</label>
              <select
                data-testid="new-field-type"
                value={form.fieldType}
                onChange={(e) => setForm((f) => ({ ...f, fieldType: e.target.value, options: [] }))}
                disabled={!!editingId}
                className="w-full px-3 py-1.5 border border-slate-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-slate-50 disabled:text-slate-400"
              >
                {FIELD_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
              {editingId && (
                <p className="text-xs text-slate-400 mt-0.5">Type cannot be changed after creation.</p>
              )}
            </div>
          </div>

          <div>
            <label className="text-xs text-slate-500 block mb-1">Display order (position)</label>
            <input
              type="number"
              value={form.position}
              onChange={(e) => setForm((f) => ({ ...f, position: parseInt(e.target.value) || 0 }))}
              className="w-24 px-3 py-1.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          {form.fieldType === "select" && (
            <div>
              <label className="text-xs text-slate-500 block mb-1">Options</label>
              <div className="flex gap-2 mb-2">
                <input
                  value={optionInput}
                  onChange={(e) => setOptionInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addOption())}
                  placeholder="Add option and press Enter"
                  className="flex-1 px-3 py-1.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <button
                  onClick={addOption}
                  className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-600 text-sm rounded-lg"
                >
                  Add
                </button>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {(form.options ?? []).map((opt) => (
                  <span
                    key={opt}
                    className="inline-flex items-center gap-1 px-2 py-0.5 bg-slate-100 text-slate-700 rounded text-xs"
                  >
                    {opt}
                    <button onClick={() => removeOption(opt)} className="opacity-60 hover:opacity-100">
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                ))}
              </div>
            </div>
          )}

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

      {/* Field list */}
      {loading ? (
        <div className="flex items-center gap-2 text-slate-400 text-sm">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading…
        </div>
      ) : fields.length === 0 ? (
        <div className="text-center py-16 text-slate-400">
          <SlidersHorizontal className="w-8 h-8 mx-auto mb-3 opacity-40" />
          <p className="text-sm">No custom fields yet.</p>
          <p className="text-xs mt-1">Create one to add structured metadata to your documents.</p>
        </div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50">
                <th className="text-left px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wide">Name</th>
                <th className="text-left px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wide">Type</th>
                <th className="text-left px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wide">Options</th>
                <th className="text-left px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wide">Pos.</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {fields.map((field) => (
                <tr key={field.id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-4 py-3 font-medium text-slate-800">{field.name}</td>
                  <td className="px-4 py-3 text-slate-500 capitalize">
                    {FIELD_TYPES.find((t) => t.value === field.fieldType)?.label ?? field.fieldType}
                  </td>
                  <td className="px-4 py-3 text-slate-500">
                    {field.fieldType === "select" && field.options.length > 0
                      ? field.options.join(", ")
                      : "—"}
                  </td>
                  <td className="px-4 py-3 text-slate-400">{field.position}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1 justify-end">
                      <button
                        onClick={() => openEdit(field)}
                        className="p-1.5 rounded hover:bg-slate-100 text-slate-400 hover:text-slate-600"
                        title="Edit"
                      >
                        <Pencil className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => handleDelete(field.id)}
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

      {/* Predefined fields by document type */}
      {fields.length > 0 && (
        <div className="mt-10">
          <h2 className="text-lg font-semibold text-slate-800 mb-1">Predefined fields by document type</h2>
          <p className="text-sm text-slate-500 mb-4">
            Fields marked predefined for a type are prompted for at upload time and shown by
            default on that document&apos;s detail page.
          </p>

          {predefinedError && <p className="text-red-500 text-xs mb-3">{predefinedError}</p>}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {DOC_TYPES.map((docType) => {
              const attached = predefined[docType.value] ?? [];
              const attachedIds = new Set(attached.map((f) => f.fieldId));
              const availableToAdd = fields.filter((f) => !attachedIds.has(f.id));

              return (
                <div
                  key={docType.value}
                  data-testid={`predefined-card-${docType.value}`}
                  className="bg-white border border-slate-200 rounded-xl p-4"
                >
                  <p className="text-sm font-semibold text-slate-700 mb-2">{docType.label}</p>

                  {attached.length === 0 ? (
                    <p className="text-xs text-slate-400 mb-2">No predefined fields.</p>
                  ) : (
                    <div className="space-y-1.5 mb-2">
                      {attached.map((f) => (
                        <div key={f.fieldId} className="flex items-center gap-2 text-xs">
                          <span className="flex-1 text-slate-700">{f.fieldName}</span>
                          <label className="flex items-center gap-1 text-slate-500 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={f.required}
                              onChange={() => handleTogglePredefinedRequired(docType.value, f)}
                              className="rounded"
                            />
                            Required
                          </label>
                          <button
                            onClick={() => handleRemovePredefined(docType.value, f.fieldId)}
                            className="p-1 rounded hover:bg-red-50 text-slate-300 hover:text-red-500"
                            title="Remove"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}

                  {addingForType === docType.value ? (
                    <div className="flex items-center gap-1.5 mt-2">
                      <select
                        data-testid={`predefined-picker-${docType.value}`}
                        value={selectedFieldToAdd}
                        onChange={(e) => setSelectedFieldToAdd(e.target.value)}
                        className="flex-1 px-2 py-1 border border-slate-200 rounded text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-500"
                      >
                        <option value="">Pick a field…</option>
                        {availableToAdd.map((f) => (
                          <option key={f.id} value={f.id}>{f.name}</option>
                        ))}
                      </select>
                      <label className="flex items-center gap-1 text-xs text-slate-500 cursor-pointer flex-shrink-0">
                        <input
                          type="checkbox"
                          checked={addRequired}
                          onChange={(e) => setAddRequired(e.target.checked)}
                          className="rounded"
                        />
                        Req.
                      </label>
                      <button
                        data-testid={`predefined-confirm-${docType.value}`}
                        onClick={() => handleAddPredefined(docType.value)}
                        disabled={!selectedFieldToAdd}
                        className="p-1 text-blue-600 hover:text-blue-800 disabled:opacity-40"
                        title="Add"
                      >
                        <Save className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => setAddingForType(null)}
                        className="p-1 text-slate-400 hover:text-slate-600"
                        title="Cancel"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ) : availableToAdd.length > 0 ? (
                    <button
                      data-testid={`predefined-add-open-${docType.value}`}
                      onClick={() => openAddPredefined(docType.value)}
                      className="px-2.5 py-1 border border-dashed border-slate-300 text-slate-400 rounded text-xs hover:border-blue-400 hover:text-blue-600 transition-colors inline-flex items-center gap-1.5"
                    >
                      <Plus className="w-3.5 h-3.5" /> Add field
                    </button>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
