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
} from "lucide-react";
import { apiUploadDocument, apiListTemplates, apiListIDPConfigs, type Template } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { DocumentType } from "@/types";

interface PendingFile {
  id: string;
  file: File;
  docType: DocumentType;
  templateId?: string;
  status: "pending" | "uploading" | "queued" | "duplicate" | "error";
  error?: string;
}

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
];
// Browsers often report an empty/unreliable File.type for some of these
// (markdown/eml especially) — fall back to extension for the client-side
// picker filter. This is a UX nicety only; the real content check happens
// server-side via magic-byte sniffing (idp/mimetype.py), never the extension.
const ACCEPTED_EXTENSIONS = [
  "pdf", "jpg", "jpeg", "png", "webp", "tif", "tiff",
  "docx", "xlsx", "pptx", "txt", "csv", "md", "markdown", "eml",
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

export default function UploadPage() {
  const router = useRouter();
  const { refresh } = useAuth();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [files, setFiles] = useState<PendingFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [defaultType, setDefaultType] = useState<DocumentType>("invoice");
  const [configs, setConfigs] = useState<any[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);

  useEffect(() => {
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

  const removeFile = (id: string) =>
    setFiles((prev) => prev.filter((f) => f.id !== id));

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

  const handleUpload = async () => {
    const pending = files.filter((f) => f.status === "pending");
    if (pending.length === 0) return;
    setUploading(true);

    let anyStored = false;
    for (const pf of pending) {
      setFiles((prev) =>
        prev.map((f) => (f.id === pf.id ? { ...f, status: "uploading" } : f))
      );

      try {
        const form = new FormData();
        form.append("files", pf.file);
        form.append("document_type", pf.docType);
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
          and email (.eml) — up to {MAX_SIZE_MB} MB each.
        </p>
      </div>

      {/* Default type selector */}
      <div className="bg-white border border-slate-200 rounded-xl p-5 mb-5">
        <p className="text-sm font-medium text-slate-700 mb-3">Default document type</p>
        <div className="flex flex-wrap gap-2">
          {DOC_TYPES.map(({ value, label }) => (
            <button
              key={value}
              onClick={() => setDefaultType(value)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors ${
                defaultType === value
                  ? "bg-blue-600 text-white border-blue-600"
                  : "bg-white text-slate-600 border-slate-200 hover:border-blue-400 hover:text-blue-700"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <p className="text-xs text-slate-400 mt-2">
          Applied to newly added files. You can override per file below.
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
          accept=".pdf,.jpg,.jpeg,.png,.webp,.tiff,.tif,.docx,.xlsx,.pptx,.txt,.csv,.md,.eml"
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
        <div className="flex items-center justify-center gap-3 text-xs text-slate-400 flex-wrap">
          <span className="flex items-center gap-1"><File className="w-3.5 h-3.5" /> PDF</span>
          <span className="flex items-center gap-1"><FileImage className="w-3.5 h-3.5" /> Image</span>
          <span className="flex items-center gap-1"><FileText className="w-3.5 h-3.5" /> Word/Text</span>
          <span className="flex items-center gap-1"><FileSpreadsheet className="w-3.5 h-3.5" /> Excel/CSV</span>
          <span className="flex items-center gap-1"><Presentation className="w-3.5 h-3.5" /> PowerPoint</span>
          <span className="flex items-center gap-1"><Mail className="w-3.5 h-3.5" /> Email</span>
        </div>
      </div>

      {/* File list */}
      {files.length > 0 && (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden mb-5">
          <div className="px-5 py-3 border-b border-slate-100 flex items-center justify-between">
            <p className="text-sm font-semibold text-slate-700">
              {files.length} file{files.length > 1 ? "s" : ""} selected
            </p>
            {!uploading && (
              <button
                onClick={() => setFiles([])}
                className="text-xs text-slate-400 hover:text-red-500 transition-colors"
              >
                Clear all
              </button>
            )}
          </div>

          <div className="divide-y divide-slate-50">
            {files.map((pf) => (
              <div key={pf.id} className="px-5 py-3.5 flex items-center gap-4">
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
                        <div className="flex gap-2 items-center">
                          <div className="relative inline-block">
                            <select
                              value={pf.docType}
                              onChange={(e) => updateType(pf.id, e.target.value as DocumentType)}
                              className="appearance-none text-xs pl-2 pr-6 py-1 rounded border border-slate-200 bg-white text-slate-600 cursor-pointer focus:outline-none focus:ring-1 focus:ring-blue-500 font-semibold"
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
      )}

      {/* IDP info box */}
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 mb-6 text-sm">
        <p className="font-semibold text-blue-800 mb-1">How processing works</p>
        <ol className="space-y-1 text-blue-700 text-xs list-decimal list-inside">
          <li>File is stored securely in object storage</li>
          <li>Text layer check — if found, OCR is skipped (faster &amp; cheaper)</li>
          <li>OCR via LiteParse for scanned documents</li>
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
    </div>
  );
}
