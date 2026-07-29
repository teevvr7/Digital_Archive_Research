"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  Upload,
  File,
  FileImage,
  FileText,
  FileSpreadsheet,
  Presentation,
  Mail,
  X,
  CheckCircle2,
  AlertCircle,
  CopyCheck,
  Loader2,
  ChevronDown,
  CheckSquare,
  Camera,
  FileCode,
  ListChecks,
  Plus,
  Save,
} from "lucide-react";
import {
  apiUploadDocument,
  apiPredefinedFields,
  apiCustomFields,
  apiListTemplates,
  apiListIDPConfigs,
  type Template,
  type IDPConfig,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { CustomFieldInput, parseCustomFieldValue } from "@/components/custom-field-input";
import { Modal } from "@/components/ui/modal";
import type { CustomField, DocumentType, PredefinedField } from "@/types";

interface PendingNewField {
  name: string;
  fieldType: string;
  options: string[];
  value: unknown;
}

interface PendingAttachField {
  fieldId: string;
  value: unknown;
}

interface PendingFile {
  id: string;
  file: File;
  docType: DocumentType;
  templateId?: string;
  status: "pending" | "uploading" | "queued" | "duplicate" | "error";
  error?: string;
  fieldValues: Record<string, unknown>;
  newFields: PendingNewField[];
  attachFields: PendingAttachField[];
}

const NEW_FIELD_TYPES = [
  { value: "text", label: "Text" },
  { value: "number", label: "Number" },
  { value: "date", label: "Date" },
  { value: "boolean", label: "Yes / No" },
  { value: "select", label: "Select (dropdown)" },
];

const DOC_TYPES: { value: DocumentType; label: string }[] = [
  { value: "invoice", label: "Invoice" },
  { value: "receipt", label: "Receipt" },
  { value: "contract", label: "Contract" },
  { value: "report", label: "Report" },
  { value: "letter", label: "Letter" },
  { value: "form", label: "Form" },
  { value: "other", label: "Other" },
];

const ACCEPTED = [
  "application/pdf",
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/tiff",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document", // .docx
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", // .xlsx
  "application/vnd.openxmlformats-officedocument.presentationml.presentation", // .pptx
  "text/plain",
  "text/csv",
  "text/markdown",
  "message/rfc822",
  "text/xml",
  "application/xml",
];
// Browsers often report an empty/unreliable File.type for some of these
// (markdown/eml/xml especially) — fall back to extension for the client-side
// picker filter. This is a UX nicety only; the real content check happens
// server-side via magic-byte sniffing (idp/mimetype.py), never the extension.
const ACCEPTED_EXTENSIONS = [
  "pdf", "jpg", "jpeg", "png", "webp", "tif", "tiff",
  "docx", "xlsx", "pptx", "txt", "csv", "md", "markdown", "eml", "xml",
];
const MAX_SIZE_MB = 50;

function isAcceptedFile(f: globalThis.File): boolean {
  if (ACCEPTED.includes(f.type)) return true;
  const ext = f.name.split(".").pop()?.toLowerCase();
  return !!ext && ACCEPTED_EXTENSIONS.includes(ext);
}

function FileIcon({ mime }: { mime: string }) {
  if (mime.startsWith("image/")) return <FileImage className="w-5 h-5 text-blue-500" />;
  if (mime === "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return <FileSpreadsheet className="w-5 h-5 text-green-600" />;
  if (mime === "application/vnd.openxmlformats-officedocument.presentationml.presentation")
    return <Presentation className="w-5 h-5 text-orange-500" />;
  if (mime === "message/rfc822") return <Mail className="w-5 h-5 text-slate-500" />;
  return <FileText className="w-5 h-5 text-red-500" />;
}

function formatSize(bytes: number) {
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`;
  return `${(bytes / 1_024).toFixed(0)} KB`;
}

/** Renders a filled-in value back to the draft-string format CustomFieldInput expects. */
function valueToDraft(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

interface FieldsModalProps {
  title: string;
  predefined: PredefinedField[];
  allFields: CustomField[];
  initialFieldValues: Record<string, unknown>;
  initialNewFields: PendingNewField[];
  initialAttachFields: PendingAttachField[];
  onSave: (
    fieldValues: Record<string, unknown>,
    newFields: PendingNewField[],
    attachFields: PendingAttachField[]
  ) => void;
  onClose: () => void;
}

/**
 * Popup for filling in a document type's predefined fields, attaching an
 * existing catalog field, or defining a brand-new one — all before the file
 * is even uploaded. Shared visual language with the Custom Fields page's
 * create form and the document detail page's inline field editor.
 */
function FieldsModal({
  title,
  predefined,
  allFields,
  initialFieldValues,
  initialNewFields,
  initialAttachFields,
  onSave,
  onClose,
}: FieldsModalProps) {
  const [drafts, setDrafts] = useState<Record<string, string>>(() => {
    const seeded: Record<string, string> = {};
    for (const field of predefined) {
      seeded[field.fieldId] = valueToDraft(initialFieldValues[field.fieldId]);
    }
    return seeded;
  });
  const [newFields, setNewFields] = useState<PendingNewField[]>(initialNewFields);
  const [attachFields, setAttachFields] = useState<PendingAttachField[]>(initialAttachFields);
  const [showAddForm, setShowAddForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [newType, setNewType] = useState("text");
  const [newOptions, setNewOptions] = useState<string[]>([]);
  const [newOptionInput, setNewOptionInput] = useState("");
  const [newValueDraft, setNewValueDraft] = useState("");
  const [showExistingPicker, setShowExistingPicker] = useState(false);
  const [pickedFieldId, setPickedFieldId] = useState("");
  const [pickedValueDraft, setPickedValueDraft] = useState("");
  const [formError, setFormError] = useState("");

  const availableExisting = allFields.filter(
    (f) =>
      !predefined.some((p) => p.fieldId === f.id) &&
      !attachFields.some((a) => a.fieldId === f.id) &&
      !newFields.some((nf) => nf.name === f.name)
  );

  const addOption = () => {
    const opt = newOptionInput.trim();
    if (!opt || newOptions.includes(opt)) return;
    setNewOptions((prev) => [...prev, opt]);
    setNewOptionInput("");
  };

  const resetAddForm = () => {
    setShowAddForm(false);
    setNewName("");
    setNewType("text");
    setNewOptions([]);
    setNewOptionInput("");
    setNewValueDraft("");
  };

  const handleAddNewField = () => {
    if (!newName.trim()) {
      setFormError("New field needs a name.");
      return;
    }
    if (newType === "select" && newOptions.length === 0) {
      setFormError("Select fields need at least one option.");
      return;
    }
    setFormError("");
    setNewFields((prev) => [
      ...prev,
      {
        name: newName.trim(),
        fieldType: newType,
        options: newOptions,
        value: parseCustomFieldValue(newType, newValueDraft),
      },
    ]);
    resetAddForm();
  };

  const removeNewField = (index: number) =>
    setNewFields((prev) => prev.filter((_, i) => i !== index));

  const resetExistingPicker = () => {
    setShowExistingPicker(false);
    setPickedFieldId("");
    setPickedValueDraft("");
  };

  const handleAttachExisting = () => {
    if (!pickedFieldId) return;
    const field = allFields.find((f) => f.id === pickedFieldId);
    if (!field) return;
    setAttachFields((prev) => [
      ...prev,
      { fieldId: pickedFieldId, value: parseCustomFieldValue(field.fieldType, pickedValueDraft) },
    ]);
    resetExistingPicker();
  };

  const removeAttachField = (index: number) =>
    setAttachFields((prev) => prev.filter((_, i) => i !== index));

  const handleSave = () => {
    const missingRequired = predefined.find(
      (f) => f.required && !drafts[f.fieldId]?.trim()
    );
    if (missingRequired) {
      setFormError(`"${missingRequired.fieldName}" is required.`);
      return;
    }
    const fieldValues: Record<string, unknown> = {};
    for (const field of predefined) {
      const draft = drafts[field.fieldId];
      if (draft != null && draft !== "") {
        fieldValues[field.fieldId] = parseCustomFieldValue(field.fieldType, draft);
      }
    }
    onSave(fieldValues, newFields, attachFields);
  };

  return (
    <Modal open onClose={onClose} title={title}>
        {predefined.length === 0 &&
          newFields.length === 0 &&
          attachFields.length === 0 &&
          !showAddForm &&
          !showExistingPicker && (
            <p className="text-xs text-slate-400 mb-3">
              No predefined fields for this document type yet.
            </p>
          )}

        <div className="space-y-3 mb-4">
          {predefined.map((field) => (
            <div key={field.fieldId}>
              <label className="text-xs text-slate-500 block mb-1">
                {field.fieldName}
                {field.required && <span className="text-red-500 ml-0.5">*</span>}
              </label>
              <CustomFieldInput
                fieldType={field.fieldType}
                options={field.options}
                value={drafts[field.fieldId] ?? ""}
                onChange={(v) => setDrafts((prev) => ({ ...prev, [field.fieldId]: v }))}
                className="w-full px-2.5 py-1.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                testId={`predefined-field-input-${field.fieldName}`}
              />
            </div>
          ))}

          {newFields.map((nf, i) => (
            <div key={`${nf.name}-${i}`} className="flex items-end gap-2">
              <div className="flex-1">
                <label className="text-xs text-slate-500 block mb-1">
                  {nf.name} <span className="text-slate-300">(new)</span>
                </label>
                <CustomFieldInput
                  fieldType={nf.fieldType}
                  options={nf.options}
                  value={valueToDraft(nf.value)}
                  onChange={(v) =>
                    setNewFields((prev) =>
                      prev.map((f, idx) =>
                        idx === i ? { ...f, value: parseCustomFieldValue(nf.fieldType, v) } : f
                      )
                    )
                  }
                  className="w-full px-2.5 py-1.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                />
              </div>
              <button
                onClick={() => removeNewField(i)}
                className="p-1.5 text-slate-300 hover:text-red-500"
                title="Remove"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}

          {attachFields.map((af, i) => {
            const field = allFields.find((f) => f.id === af.fieldId);
            if (!field) return null;
            return (
              <div key={af.fieldId} className="flex items-end gap-2">
                <div className="flex-1">
                  <label className="text-xs text-slate-500 block mb-1">{field.name}</label>
                  <CustomFieldInput
                    fieldType={field.fieldType}
                    options={field.options}
                    value={valueToDraft(af.value)}
                    onChange={(v) =>
                      setAttachFields((prev) =>
                        prev.map((a, idx) =>
                          idx === i ? { ...a, value: parseCustomFieldValue(field.fieldType, v) } : a
                        )
                      )
                    }
                    className="w-full px-2.5 py-1.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                  />
                </div>
                <button
                  onClick={() => removeAttachField(i)}
                  className="p-1.5 text-slate-300 hover:text-red-500"
                  title="Remove"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            );
          })}
        </div>

        {showExistingPicker ? (
          <div className="border border-slate-200 rounded-lg p-3 mb-4 space-y-2.5 bg-slate-50">
            <select
              value={pickedFieldId}
              onChange={(e) => { setPickedFieldId(e.target.value); setPickedValueDraft(""); }}
              className="w-full px-2.5 py-1.5 border border-slate-200 rounded-lg text-xs bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">Pick a field…</option>
              {availableExisting.map((f) => (
                <option key={f.id} value={f.id}>{f.name}</option>
              ))}
            </select>

            {pickedFieldId && (() => {
              const field = allFields.find((f) => f.id === pickedFieldId);
              if (!field) return null;
              return (
                <div>
                  <label className="text-xs text-slate-500 block mb-1">Value for this file</label>
                  <CustomFieldInput
                    fieldType={field.fieldType}
                    options={field.options}
                    value={pickedValueDraft}
                    onChange={setPickedValueDraft}
                    className="w-full px-2.5 py-1.5 border border-slate-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                  />
                </div>
              );
            })()}

            <div className="flex gap-1.5">
              <button
                onClick={handleAttachExisting}
                disabled={!pickedFieldId}
                className="flex items-center gap-1 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-40 text-white text-xs rounded-lg"
              >
                <Save className="w-3 h-3" /> Add field
              </button>
              <button
                onClick={resetExistingPicker}
                className="px-3 py-1.5 border border-slate-200 hover:bg-white text-slate-600 text-xs rounded-lg"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : showAddForm ? (
          <div className="border border-slate-200 rounded-lg p-3 mb-4 space-y-2.5 bg-slate-50">
            <div className="grid grid-cols-2 gap-2">
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Field name"
                className="px-2.5 py-1.5 border border-slate-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <select
                value={newType}
                onChange={(e) => { setNewType(e.target.value); setNewOptions([]); }}
                className="px-2.5 py-1.5 border border-slate-200 rounded-lg text-xs bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {NEW_FIELD_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>

            {newType === "select" && (
              <div>
                <div className="flex gap-1.5 mb-1.5">
                  <input
                    value={newOptionInput}
                    onChange={(e) => setNewOptionInput(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addOption())}
                    placeholder="Add option, press Enter"
                    className="flex-1 px-2.5 py-1 border border-slate-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  <button
                    onClick={addOption}
                    className="px-2.5 py-1 bg-slate-200 hover:bg-slate-300 text-slate-600 text-xs rounded-lg"
                  >
                    Add
                  </button>
                </div>
                <div className="flex flex-wrap gap-1">
                  {newOptions.map((o) => (
                    <span key={o} className="inline-flex items-center gap-1 px-2 py-0.5 bg-white border border-slate-200 rounded text-xs">
                      {o}
                      <button onClick={() => setNewOptions((prev) => prev.filter((x) => x !== o))} className="opacity-60 hover:opacity-100">
                        <X className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div>
              <label className="text-xs text-slate-500 block mb-1">Value for this file</label>
              <CustomFieldInput
                fieldType={newType}
                options={newOptions}
                value={newValueDraft}
                onChange={setNewValueDraft}
                className="w-full px-2.5 py-1.5 border border-slate-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
              />
            </div>

            <div className="flex gap-1.5">
              <button
                onClick={handleAddNewField}
                className="flex items-center gap-1 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded-lg"
              >
                <Save className="w-3 h-3" /> Add field
              </button>
              <button
                onClick={resetAddForm}
                className="px-3 py-1.5 border border-slate-200 hover:bg-white text-slate-600 text-xs rounded-lg"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="flex gap-2 mb-4">
            <button
              onClick={() => setShowExistingPicker(true)}
              disabled={availableExisting.length === 0}
              className="flex-1 inline-flex items-center justify-center gap-1.5 px-2.5 py-1.5 border border-dashed border-slate-300 text-slate-500 rounded-lg text-xs hover:border-blue-400 hover:text-blue-600 transition-colors disabled:opacity-40 disabled:hover:border-slate-300 disabled:hover:text-slate-500"
              title={availableExisting.length === 0 ? "No other fields to reuse yet" : undefined}
            >
              <ListChecks className="w-3.5 h-3.5" /> Use existing field
            </button>
            <button
              onClick={() => setShowAddForm(true)}
              className="flex-1 inline-flex items-center justify-center gap-1.5 px-2.5 py-1.5 border border-dashed border-slate-300 text-slate-500 rounded-lg text-xs hover:border-blue-400 hover:text-blue-600 transition-colors"
            >
              <Plus className="w-3.5 h-3.5" /> Create new field
            </button>
          </div>
        )}

        {formError && <p className="text-xs text-red-600 mb-3">{formError}</p>}

        <div className="flex gap-2">
          <button
            onClick={handleSave}
            className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors"
          >
            Save details
          </button>
          <button
            onClick={onClose}
            className="px-4 py-2 border border-slate-200 hover:bg-slate-50 text-slate-600 text-sm rounded-lg transition-colors"
          >
            Cancel
          </button>
        </div>
    </Modal>
  );
}

export default function UploadPage() {
  const router = useRouter();
  const { refresh } = useAuth();
  const inputRef = useRef<HTMLInputElement>(null);
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [files, setFiles] = useState<PendingFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [defaultType, setDefaultType] = useState<DocumentType>("other");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkType, setBulkType] = useState<DocumentType>("other");
  const [predefinedFields, setPredefinedFields] = useState<Record<string, PredefinedField[]>>({});
  const [allFields, setAllFields] = useState<CustomField[]>([]);
  const [fieldsModalTarget, setFieldsModalTarget] = useState<
    { mode: "single"; fileId: string } | { mode: "bulk"; fileIds: string[] } | null
  >(null);
  const [configs, setConfigs] = useState<IDPConfig[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);

  useEffect(() => {
    apiPredefinedFields().then(setPredefinedFields).catch(() => {});
    apiCustomFields().then(setAllFields).catch(() => {});

    const fetchConfigsAndTemplates = async () => {
      try {
        const [configRes, templateRes] = await Promise.all([
          apiListIDPConfigs(),
          apiListTemplates(),
        ]);
        setConfigs(configRes.configs);
        setTemplates(templateRes);
      } catch (e) {
        console.error("Failed to load IDP configs/templates:", e);
      }
    };
    fetchConfigsAndTemplates();
  }, []);

  const addFiles = useCallback(
    (incoming: FileList | null) => {
      if (!incoming) return;
      const newItems: PendingFile[] = [];
      for (const f of Array.from(incoming)) {
        if (!isAcceptedFile(f)) continue;
        if (f.size > MAX_SIZE_MB * 1_048_576) continue;

        // Auto-assign default template if exists for the default document type
        const docTypeConfig = configs.find((c) => c.name.toLowerCase() === defaultType.toLowerCase());
        const defaultTpl = docTypeConfig
          ? templates.find((t) => t.documentTypeId === docTypeConfig.documentTypeId && t.isDefault)
          : undefined;

        newItems.push({
          id: `${Date.now()}-${Math.random()}`,
          file: f,
          docType: defaultType,
          templateId: defaultTpl?.id,
          status: "pending",
          fieldValues: {},
          newFields: [],
          attachFields: [],
        });
      }
      setFiles((prev) => [...prev, ...newItems]);
    },
    [defaultType, configs, templates]
  );

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    addFiles(e.dataTransfer.files);
  };

  const removeFile = (id: string) => {
    setFiles((prev) => prev.filter((f) => f.id !== id));
    setSelectedIds((prev) => {
      if (!prev.has(id)) return prev;
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  };

  const updateType = (id: string, docType: DocumentType) =>
    setFiles((prev) =>
      prev.map((f) => {
        if (f.id === id) {
          // Sync and find default template for this newly selected document type
          const docTypeConfig = configs.find((c) => c.name.toLowerCase() === docType.toLowerCase());
          const defaultTpl = docTypeConfig
            ? templates.find((t) => t.documentTypeId === docTypeConfig.documentTypeId && t.isDefault)
            : undefined;
          return { ...f, docType, templateId: defaultTpl?.id };
        }
        return f;
      })
    );

  const updateTemplate = (id: string, templateId: string) =>
    setFiles((prev) =>
      prev.map((f) => (f.id === id ? { ...f, templateId: templateId || undefined } : f))
    );

  // Only pending files have an editable type — once uploading/queued/etc.,
  // the type was already submitted with the request.
  const pendingFiles = files.filter((f) => f.status === "pending");

  const toggleSelect = (id: string) =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const toggleSelectAll = () => {
    setSelectedIds((prev) =>
      prev.size === pendingFiles.length ? new Set() : new Set(pendingFiles.map((f) => f.id))
    );
  };

  const applyBulkType = () => {
    setFiles((prev) =>
      prev.map((f) => (selectedIds.has(f.id) ? { ...f, docType: bulkType } : f))
    );
    setSelectedIds(new Set());
  };

  const handleFieldsModalSave = (
    fieldValues: Record<string, unknown>,
    newFields: PendingNewField[],
    attachFields: PendingAttachField[]
  ) => {
    if (!fieldsModalTarget) return;
    const targetIds =
      fieldsModalTarget.mode === "single" ? [fieldsModalTarget.fileId] : fieldsModalTarget.fileIds;
    setFiles((prev) =>
      prev.map((f) => (targetIds.includes(f.id) ? { ...f, fieldValues, newFields, attachFields } : f))
    );
    setFieldsModalTarget(null);
    if (fieldsModalTarget.mode === "bulk") setSelectedIds(new Set());
  };

  const handleUpload = async () => {
    const pending = files.filter((f) => f.status === "pending");
    if (pending.length === 0) return;
    setUploading(true);
    setSelectedIds(new Set());

    let anyStored = false;
    for (const pf of pending) {
      setFiles((prev) =>
        prev.map((f) => (f.id === pf.id ? { ...f, status: "uploading" } : f))
      );

      try {
        const form = new FormData();
        form.append("files", pf.file);
        form.append("document_type", pf.docType);
        if (Object.keys(pf.fieldValues).length > 0) {
          form.append("field_values", JSON.stringify(pf.fieldValues));
        }
        if (pf.newFields.length > 0) {
          form.append("new_fields", JSON.stringify(pf.newFields));
        }
        if (pf.attachFields.length > 0) {
          form.append("attach_fields", JSON.stringify(pf.attachFields));
        }
        if (pf.templateId) {
          form.append("template_id", pf.templateId);
        }
        const result = await apiUploadDocument(form);
        const isDuplicate = result.duplicates.length > 0;
        if (!isDuplicate) anyStored = true;
        setFiles((prev) =>
          prev.map((f) =>
            f.id === pf.id ? { ...f, status: isDuplicate ? "duplicate" : "queued" } : f
          )
        );
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : "Upload failed";
        setFiles((prev) =>
          prev.map((f) => (f.id === pf.id ? { ...f, status: "error", error: msg } : f))
        );
      }
    }

    setUploading(false);
    // A new file bumped tenant storage server-side — refresh so the sidebar
    // storage meter reflects it (duplicates don't change usage).
    if (anyStored) await refresh();
    // A file may have just created and/or attached a predefined field
    // (new-field or use-existing-field flows) — refetch so the next file
    // added in this same session sees it without needing a page reload.
    apiPredefinedFields().then(setPredefinedFields).catch(() => {});
  };

  const isTerminal = (s: PendingFile["status"]) => s === "queued" || s === "duplicate";
  const allDone = files.length > 0 && files.every((f) => isTerminal(f.status));

  // Navigate to documents once every file has reached a terminal state.
  useEffect(() => {
    if (allDone) {
      const timerId = setTimeout(() => router.push("/documents"), 800);
      return () => clearTimeout(timerId);
    }
  }, [allDone, router]);
  const pendingCount = files.filter((f) => f.status === "pending").length;

  return (
    <div className="p-8 max-w-3xl">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-slate-900">Upload Documents</h1>
        <p className="text-slate-500 text-sm mt-0.5">
          Supports PDF, scans, images, Word/Excel/PowerPoint, text/CSV/Markdown,
          email (.eml), and e-invoices (UBL/MyInvois XML) — up to {MAX_SIZE_MB} MB each.
        </p>
      </div>

      {/* Drop zone */}
      <div
        className={`upload-zone rounded-xl p-10 text-center cursor-pointer mb-5 ${dragging ? "dragover" : ""}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.jpg,.jpeg,.png,.webp,.tiff,.tif,.docx,.xlsx,.pptx,.txt,.csv,.md,.eml,.xml"
          className="hidden"
          onChange={(e) => addFiles(e.target.files)}
        />
        {/* Camera-only input — capture="environment" opens the phone's rear
            camera directly (ignored by browsers with no camera, e.g. desktop). */}
        <input
          ref={cameraInputRef}
          type="file"
          accept="image/*"
          capture="environment"
          className="hidden"
          onChange={(e) => addFiles(e.target.files)}
        />
        <div className="w-14 h-14 rounded-2xl bg-blue-100 flex items-center justify-center mx-auto mb-4">
          <Upload className="w-7 h-7 text-blue-600" />
        </div>
        <p className="font-semibold text-slate-700 mb-1">
          {dragging ? "Drop files here" : "Drag & drop files here"}
        </p>
        <p className="text-slate-400 text-sm mb-4">or click to browse</p>
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); cameraInputRef.current?.click(); }}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 mb-4 rounded-lg border border-slate-200 text-slate-600 text-xs font-medium hover:border-blue-400 hover:text-blue-700 transition-colors"
        >
          <Camera className="w-3.5 h-3.5" /> Take a photo
        </button>
        <div className="flex items-center justify-center gap-3 text-xs text-slate-400 flex-wrap">
          <span className="flex items-center gap-1"><File className="w-3.5 h-3.5" /> PDF</span>
          <span className="flex items-center gap-1"><FileImage className="w-3.5 h-3.5" /> Image</span>
          <span className="flex items-center gap-1"><FileText className="w-3.5 h-3.5" /> Word/Text</span>
          <span className="flex items-center gap-1"><FileSpreadsheet className="w-3.5 h-3.5" /> Excel/CSV</span>
          <span className="flex items-center gap-1"><Presentation className="w-3.5 h-3.5" /> PowerPoint</span>
          <span className="flex items-center gap-1"><Mail className="w-3.5 h-3.5" /> Email</span>
          <span className="flex items-center gap-1"><FileCode className="w-3.5 h-3.5" /> E-invoice (XML)</span>
        </div>
      </div>

      {/* File list */}
      {files.length > 0 && (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden mb-5">
          <div className="px-5 py-3 border-b border-slate-100 flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-3">
              {pendingFiles.length > 0 && !uploading && (
                <input
                  type="checkbox"
                  checked={selectedIds.size > 0 && selectedIds.size === pendingFiles.length}
                  onChange={toggleSelectAll}
                  className="w-4 h-4 rounded border-slate-300 cursor-pointer flex-shrink-0"
                  title="Select all"
                />
              )}
              <p className="text-sm font-semibold text-slate-700">
                {files.length} file{files.length > 1 ? "s" : ""} added
              </p>
            </div>
            {!uploading && (
              <button
                onClick={() => {
                  setFiles([]);
                  setSelectedIds(new Set());
                }}
                className="text-xs text-slate-400 hover:text-red-500 transition-colors"
              >
                Clear all
              </button>
            )}
          </div>

          {/* Bulk type-change toolbar — only meaningful for still-pending files */}
          {selectedIds.size > 0 && (
            <div className="px-5 py-2.5 border-b border-blue-100 bg-blue-50 flex items-center gap-2 flex-wrap">
              <CheckSquare className="w-4 h-4 text-blue-600 flex-shrink-0" />
              <span className="text-sm font-medium text-blue-800">
                {selectedIds.size} selected
              </span>
              <div className="relative inline-block ml-2">
                <select
                  value={bulkType}
                  onChange={(e) => setBulkType(e.target.value as DocumentType)}
                  className="appearance-none text-xs pl-2.5 pr-6 py-1.5 rounded-lg border border-blue-200 bg-white text-slate-700 cursor-pointer focus:outline-none focus:ring-1 focus:ring-blue-500"
                >
                  {DOC_TYPES.map(({ value, label }) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
                <ChevronDown className="absolute right-1.5 top-1/2 -translate-y-1/2 w-3 h-3 text-slate-400 pointer-events-none" />
              </div>
              <button
                onClick={applyBulkType}
                className="text-xs font-medium px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
              >
                Apply to {selectedIds.size}
              </button>
              <button
                onClick={() =>
                  setFieldsModalTarget({ mode: "bulk", fileIds: Array.from(selectedIds) })
                }
                className="text-xs font-medium px-3 py-1.5 border border-blue-200 bg-white hover:bg-blue-100 text-blue-700 rounded-lg transition-colors inline-flex items-center gap-1.5"
              >
                <ListChecks className="w-3.5 h-3.5" /> Fill details for {selectedIds.size}
              </button>
            </div>
          )}

          <div className="max-h-[420px] overflow-y-auto">
          <div className="divide-y divide-slate-50">
            {files.map((pf) => (
              <div key={pf.id} className="px-5 py-3.5 flex items-center gap-4">
                {pf.status === "pending" ? (
                  <input
                    type="checkbox"
                    checked={selectedIds.has(pf.id)}
                    onChange={() => toggleSelect(pf.id)}
                    className="w-4 h-4 rounded border-slate-300 cursor-pointer flex-shrink-0"
                  />
                ) : (
                  <span className="w-4 flex-shrink-0" />
                )}
                <div className="w-9 h-9 rounded-lg bg-slate-100 flex items-center justify-center flex-shrink-0">
                  <FileIcon mime={pf.file.type} />
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="text-sm font-medium text-slate-700 truncate">
                      {pf.file.name}
                    </span>
                    <span className="text-xs text-slate-400 flex-shrink-0">
                      {formatSize(pf.file.size)}
                    </span>
                  </div>

                  {pf.status === "uploading" ? (
                    <div className="flex items-center gap-1.5 text-xs text-blue-600">
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      Uploading…
                    </div>
                  ) : pf.status === "queued" ? (
                    <div className="flex items-center gap-1 text-xs text-green-600">
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      Added to processing queue
                    </div>
                  ) : pf.status === "duplicate" ? (
                    <div className="flex items-center gap-1 text-xs text-amber-600">
                      <CopyCheck className="w-3.5 h-3.5" />
                      Already archived — identical file skipped
                    </div>
                  ) : pf.status === "error" ? (
                    <div className="flex items-center gap-1 text-xs text-red-500">
                      <AlertCircle className="w-3.5 h-3.5" />
                      {pf.error ?? "Upload failed"}
                    </div>
                  ) : (
                    (() => {
                      const docTypeConfig = configs.find((c) => c.name.toLowerCase() === pf.docType.toLowerCase());
                      const matchingTemplates = docTypeConfig
                        ? templates.filter((t) => t.documentTypeId === docTypeConfig.documentTypeId)
                        : [];

                      return (
                        <div className="flex items-center gap-1.5">
                          <div className="relative inline-block">
                            <select
                              value={pf.docType}
                              onChange={(e) => updateType(pf.id, e.target.value as DocumentType)}
                              className="appearance-none text-xs pl-2 pr-6 py-1 rounded border border-slate-200 bg-white text-slate-600 cursor-pointer focus:outline-none focus:ring-1 focus:ring-blue-500"
                            >
                              {DOC_TYPES.map(({ value, label }) => (
                                <option key={value} value={value}>{label}</option>
                              ))}
                            </select>
                            <ChevronDown className="absolute right-1.5 top-1/2 -translate-y-1/2 w-3 h-3 text-slate-400 pointer-events-none" />
                          </div>

                          {matchingTemplates.length > 0 && (
                            <div className="relative inline-block">
                              <select
                                value={pf.templateId || ""}
                                onChange={(e) => updateTemplate(pf.id, e.target.value)}
                                className="appearance-none text-xs pl-2 pr-6 py-1 rounded border border-slate-200 bg-slate-50 text-slate-600 cursor-pointer focus:outline-none focus:ring-1 focus:ring-blue-500 font-medium"
                              >
                                <option value="">Default Strategy</option>
                                {matchingTemplates.map((t) => (
                                  <option key={t.id} value={t.id}>
                                    {t.name} {t.isDefault ? "(Default)" : ""}
                                  </option>
                                ))}
                              </select>
                              <ChevronDown className="absolute right-1.5 top-1/2 -translate-y-1/2 w-3 h-3 text-slate-400 pointer-events-none" />
                            </div>
                          )}

                          <button
                            onClick={() => setFieldsModalTarget({ mode: "single", fileId: pf.id })}
                            className={`relative p-1 rounded border transition-colors ${
                              Object.keys(pf.fieldValues).length > 0 ||
                              pf.newFields.length > 0 ||
                              pf.attachFields.length > 0
                                ? "border-blue-300 bg-blue-50 text-blue-600"
                                : "border-slate-200 text-slate-400 hover:border-blue-400 hover:text-blue-600"
                            }`}
                            title="Fill in details for this file"
                          >
                            <ListChecks className="w-3.5 h-3.5" />
                            {(Object.keys(pf.fieldValues).length > 0 ||
                              pf.newFields.length > 0 ||
                              pf.attachFields.length > 0) && (
                              <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-blue-500" />
                            )}
                          </button>
                        </div>
                      );
                    })()
                  )}
                </div>

                {pf.status === "pending" && (
                  <button
                    onClick={() => removeFile(pf.id)}
                    className="p-1 rounded hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors flex-shrink-0"
                  >
                    <X className="w-4 h-4" />
                  </button>
                )}
                {pf.status === "uploading" && (
                  <Loader2 className="w-4 h-4 text-blue-500 animate-spin flex-shrink-0" />
                )}
              </div>
            ))}
          </div>
          </div>
        </div>
      )}

      {/* IDP info box */}
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 mb-6 text-sm">
        <p className="font-semibold text-blue-800 mb-1">How processing works</p>
        <ol className="space-y-1 text-blue-700 text-xs list-decimal list-inside">
          <li>File is stored securely in object storage</li>
          <li>Text layer check — if found, OCR is skipped (faster &amp; cheaper)</li>
          <li>OCR via RapidOCR for scanned documents</li>
          <li>AI extraction (Qwen2.5-VL) for structured data on supported types</li>
          <li>Results indexed for full-text search</li>
        </ol>
      </div>

      {/* Upload button */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleUpload}
          disabled={uploading || allDone || pendingCount === 0}
          className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-6 py-2.5 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {uploading ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" /> Uploading…
            </>
          ) : allDone ? (
            <>
              <CheckCircle2 className="w-4 h-4" /> Done!
            </>
          ) : (
            <>
              <Upload className="w-4 h-4" />{" "}
              {pendingCount > 0
                ? `Upload ${pendingCount} file${pendingCount > 1 ? "s" : ""}`
                : "Upload files"}
            </>
          )}
        </button>
        <button
          onClick={() => router.push("/documents")}
          className="px-4 py-2.5 border border-slate-200 text-slate-600 hover:bg-slate-50 rounded-lg text-sm font-medium transition-colors"
        >
          Cancel
        </button>
      </div>

      {fieldsModalTarget && (() => {
        if (fieldsModalTarget.mode === "single") {
          const target = files.find((f) => f.id === fieldsModalTarget.fileId);
          if (!target) return null;
          return (
            <FieldsModal
              title={`Add details — ${target.file.name}`}
              predefined={predefinedFields[target.docType] ?? []}
              allFields={allFields}
              initialFieldValues={target.fieldValues}
              initialNewFields={target.newFields}
              initialAttachFields={target.attachFields}
              onSave={handleFieldsModalSave}
              onClose={() => setFieldsModalTarget(null)}
            />
          );
        }
        const bulkDocType =
          files.find((f) => f.id === fieldsModalTarget.fileIds[0])?.docType ?? "other";
        return (
          <FieldsModal
            title={`Add details — ${fieldsModalTarget.fileIds.length} files`}
            predefined={predefinedFields[bulkDocType] ?? []}
            allFields={allFields}
            initialFieldValues={{}}
            initialNewFields={[]}
            initialAttachFields={[]}
            onSave={handleFieldsModalSave}
            onClose={() => setFieldsModalTarget(null)}
          />
        );
      })()}
    </div>
  );
}
