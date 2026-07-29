/**
 * Typed API client for the DataWiz backend.
 *
 * Attaches the Supabase access token as a Bearer header on every request.
 * All methods return camelCase objects matching the backend CamelModel schemas.
 */

import { supabase } from "@/lib/supabase";
import type { Correspondent, CustomField, Document, ActivityEvent, FieldValue, PredefinedField, SavedView, SearchListResponse, Tag } from "@/types";

function getBaseUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (typeof window !== "undefined") {
    const host = window.location.hostname || "localhost";
    if (envUrl) {
      return envUrl.replace(/localhost|127\.0\.0\.1/, host);
    }
    return `http://${host}:8000/api`;
  }
  return envUrl ?? "http://127.0.0.1:8000/api";
}

// ---- Shared types --------------------------------------------------------

export interface AuthUser {
  id: string;
  tenantId: string;
  email: string;
  name: string;
  role: string;
  avatarInitials: string;
  createdAt: string;
  lastLoginAt: string | null;
}

export interface AuthTenant {
  id: string;
  name: string;
  plan: string;
  storageUsedBytes: number;
  storageLimitBytes: number;
  createdAt: string;
  /** This tenant's trash-retention override in days, or null to use the default. */
  trashRetentionDays: number | null;
  /** Resolved retention window (the override, or the global default) — use this for countdowns. */
  effectiveTrashRetentionDays: number;
}

export interface DashboardStats {
  totalDocuments: number;
  processed: number;
  inPipeline: number;
  failed: number;
  storageUsedBytes: number;
  storageLimitBytes: number;
  documentsCount: number;
  /** Non-trashed document counts by family: pdf/image/office/text/email/other. */
  documentsByFamily: Record<string, number>;
}

export interface DashboardResponse {
  stats: DashboardStats;
  recentDocuments: Document[];
  activity: ActivityEvent[];
}

export interface DocumentListResponse {
  items: Document[];
  total: number;
  page: number;
  pageSize: number;
  /** Filenames skipped because identical content already exists for this tenant. */
  duplicates: string[];
}

// ---- Internal fetch helpers ----------------------------------------------

async function authHeaders(): Promise<HeadersInit> {
  const { data } = await supabase.auth.getSession();

  const token = data.session?.access_token;
  if (!token) throw new Error("Not authenticated");
  return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${getBaseUrl()}${path}`, { headers: await authHeaders() });
  if (!res.ok) throw new Error(`GET ${path} → ${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const headers = await authHeaders();
  const res = await fetch(`${getBaseUrl()}${path}`, {
    method: "POST",
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`POST ${path} → ${res.status} ${await res.text()}`);
  // 204 No Content — return undefined (typed as T via void callers, e.g. tag assign)
  if (res.status === 204) return undefined as unknown as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

async function put<T>(path: string, body?: unknown): Promise<T> {
  const headers = await authHeaders();
  const res = await fetch(`${getBaseUrl()}${path}`, {
    method: "PUT",
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`PUT ${path} → ${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

async function patch_<T>(path: string, body?: unknown): Promise<T> {
  const headers = await authHeaders();
  const res = await fetch(`${getBaseUrl()}${path}`, {
    method: "PATCH",
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`PATCH ${path} → ${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

async function delete_<T>(path: string): Promise<T> {
  const headers = await authHeaders();
  const res = await fetch(`${getBaseUrl()}${path}`, { method: "DELETE", headers });
  if (!res.ok) throw new Error(`DELETE ${path} → ${res.status} ${await res.text()}`);
  // 204 No Content — return undefined (typed as T via void callers)
  if (res.status === 204) return undefined as unknown as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

async function postForm<T>(path: string, form: FormData): Promise<T> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new Error("Not authenticated");
  const res = await fetch(`${getBaseUrl()}${path}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (!res.ok) throw new Error(`POST ${path} → ${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}


// ---- Auth ----------------------------------------------------------------

/**
 * Create a new account via the backend (Supabase admin API, pre-confirmed).
 * Unauthenticated — no session exists yet, so this bypasses `authHeaders()`.
 */
export async function apiSignup(email: string, password: string): Promise<void> {
  const res = await fetch(`${getBaseUrl()}/auth/signup`, {

    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    let detail = await res.text();
    try {
      detail = (JSON.parse(detail).detail as string) ?? detail;
    } catch {
      /* non-JSON body — keep raw text */
    }
    throw new Error(detail || `Sign up failed (${res.status})`);
  }
}

export const apiBootstrap = () =>
  post<{ user: AuthUser; tenant: AuthTenant }>("/auth/bootstrap");

export const apiMe = () =>
  get<{ user: AuthUser; tenant: AuthTenant }>("/auth/me");

// ---- Dashboard -----------------------------------------------------------

export const apiDashboard = () => get<DashboardResponse>("/dashboard");

// ---- Documents -----------------------------------------------------------

export type DocumentsQuery = {
  status?: string;
  type?: string;
  tag_id?: string;
  correspondent_id?: string;
  date_from?: string;
  date_to?: string;
  amount_min?: number;
  amount_max?: number;
  vendor?: string;
  inbox?: boolean;
  sort?: string;
  q?: string;
  page?: number;
  trashed?: boolean;
  custom_field_id?: string;
  custom_field_value?: string;
  custom_field_min?: number;
  custom_field_max?: number;
  custom_field_date_from?: string;
  custom_field_date_to?: string;
};

export const apiDocuments = (query: DocumentsQuery = {}) => {
  const params = new URLSearchParams(
    Object.fromEntries(
      Object.entries(query)
        .filter(([, v]) => v !== undefined)
        .map(([k, v]) => [k, String(v)])
    )
  ).toString();
  return get<DocumentListResponse>(`/documents${params ? `?${params}` : ""}`);
};

export const apiDocument = (id: string) => get<Document>(`/documents/${id}`);

/** Returns a short-lived signed URL; open it in a new tab to trigger download.
 * Logs a download activity event server-side — only call this for an explicit
 * user download action, never for rendering the inline preview (use
 * apiPreviewUrl for that). */
export const apiDownloadUrl = (id: string) =>
  get<{ url: string }>(`/documents/${id}/download`);

/** Returns a short-lived signed URL for inline viewing. Unlike apiDownloadUrl,
 * does not log a download activity event — safe to call on every document
 * detail page load. */
export const apiPreviewUrl = (id: string) =>
  get<{ url: string }>(`/documents/${id}/preview`);

/** Returns a short-lived signed thumbnail URL. Rejects with 404 if none was generated. */
export const apiThumbnailUrl = (id: string) =>
  get<{ url: string }>(`/documents/${id}/thumbnail`);

export const apiUploadDocument = (form: FormData) =>
  postForm<DocumentListResponse>("/documents", form);

export const apiRetryDocument = (id: string) =>
  post<Document>(`/documents/${id}/retry`);

export const apiExtractDocument = (id: string) =>
  post<Document>(`/documents/${id}/extract`);

export const apiExtractMissing = () =>
  post<{ enqueued: number }>("/documents/extract-missing");

export type DocumentPatch = {
  title?: string;
  documentType?: string;
  documentDate?: string | null;
  correspondentId?: string | null;
  /** Shallow merge into extracted_data — only listed keys are overwritten. */
  extractedDataPatch?: Record<string, unknown>;
};

export const apiPatchDocument = (id: string, patch: DocumentPatch) =>
  patch_<Document>(`/documents/${id}`, patch);

export const apiTrashDocument = (id: string) =>
  delete_<Document>(`/documents/${id}`);

export const apiRestoreDocument = (id: string) =>
  post<Document>(`/documents/${id}/restore`);

export const apiEmptyTrash = () =>
  post<{ deleted: number }>("/documents/empty-trash");

export const apiPermanentDelete = (id: string) =>
  delete_<void>(`/documents/${id}/permanent`);

// ---- Search (Milestone D) ------------------------------------------------

export type SearchQuery = {
  q: string;
  type?: string;
  date?: string;
  status?: string;
  page?: number;
};

export const apiSearch = (query: SearchQuery) => {
  const params = new URLSearchParams(
    Object.fromEntries(
      Object.entries(query)
        .filter(([, v]) => v !== undefined && v !== "")
        .map(([k, v]) => [k, String(v)])
    )
  ).toString();
  return get<SearchListResponse>(`/search?${params}`);
};

// ---- Settings --------------------------------------------------------------

/**
 * Update organisation settings (name, trash-retention override). Admin-only
 * (backend enforces via require_admin). Pass `trashRetentionDays: null` to
 * clear the override and fall back to the global default.
 */
export const apiUpdateTenant = (name: string, trashRetentionDays: number | null) =>
  patch_<AuthTenant>("/auth/tenant", { name, trashRetentionDays });

// ---- Team / users (Level 4) ------------------------------------------------

/** Every member of the tenant. `lastLoginAt === null` means the invite is pending. */
export const apiListUsers = () => get<AuthUser[]>("/auth/users");

/** Invite a teammate by email. Admin-only. */
export const apiInviteUser = (email: string, name: string, role: string) =>
  post<AuthUser>("/auth/users/invite", { email, name, role });

/** Change a teammate's role. Admin-only; backend refuses to demote the last admin. */
export const apiUpdateUserRole = (userId: string, role: string) =>
  patch_<AuthUser>(`/auth/users/${userId}/role`, { role });

/** Remove a teammate from the tenant. Admin-only; backend refuses self-removal
 *  and removing the last admin. */
export const apiRemoveUser = (userId: string) => delete_<void>(`/auth/users/${userId}`);

// ---- Activity / audit trail -------------------------------------------------

export interface ActivityListResponse {
  items: ActivityEvent[];
  total: number;
  page: number;
  pageSize: number;
}

/** Paginated audit-trail feed. Pass `documentId` for a single document's
 * History tab, or omit it for the org-wide feed (Settings > Activity). */
export const apiActivity = (opts: { documentId?: string; page?: number } = {}) => {
  const params = new URLSearchParams(
    Object.fromEntries(
      Object.entries(opts)
        .filter(([, v]) => v !== undefined)
        .map(([k, v]) => [k === "documentId" ? "document_id" : k, String(v)])
    )
  ).toString();
  return get<ActivityListResponse>(`/activity${params ? `?${params}` : ""}`);
};

// ---- IDP Config -----------------------------------------------------------

export interface IDPConfig {
  documentTypeId: string;
  name: string;
  extractionMethod: string;
  jsonSchema: Record<string, unknown> | null;
  instruction: string;
  rules: string;
  isCustomized: boolean;
  isSystem: boolean;
}

export interface IDPConfigUpdateRequest {
  extractionMethod: string;
  jsonSchema?: Record<string, unknown> | null;
  instruction?: string | null;
  rules?: string | null;
}

export const apiGetIDPConfig = (documentTypeId: string) =>
  get<IDPConfig>(`/idp/config/${documentTypeId}`);

export const apiUpdateIDPConfig = (documentTypeId: string, body: IDPConfigUpdateRequest) =>
  post<IDPConfig>(`/idp/config/${documentTypeId}`, body);

export const apiListIDPConfigs = () =>
  get<{ configs: IDPConfig[] }>("/idp/config");

export interface DocumentTypeCreateRequest {
  name: string;
  description?: string | null;
  extractionMethod?: string;
}

export const apiCreateDocumentType = (body: DocumentTypeCreateRequest) =>
  post<IDPConfig>("/idp/config/document-types", body);

export const apiDeleteDocumentType = (id: string) =>
  delete_<void>(`/idp/config/document-types/${id}`);


// ---- Templates ------------------------------------------------------------

export interface Template {
  id: string;
  documentTypeId: string;
  name: string;
  isDefault: boolean;
  useImage: boolean;
  useOcr: boolean;
  extractionMethod: string;
  jsonSchema: Record<string, unknown> | null;
  instruction: string;
  rules: string;
  status: string;
}

export interface TemplateCreateRequest {
  documentTypeId: string;
  name: string;
  extractionMethod: string;
  jsonSchema: Record<string, unknown>;
  instruction?: string | null;
  rules?: string | null;
  useImage: boolean;
  useOcr: boolean;
}

export interface TemplateUpdateRequest {
  name: string;
  extractionMethod: string;
  jsonSchema: Record<string, unknown>;
  instruction?: string | null;
  rules?: string | null;
  useImage: boolean;
  useOcr: boolean;
}

export const apiListTemplates = () =>
  get<Template[]>("/idp/config/templates");

export const apiCreateTemplate = (body: TemplateCreateRequest) =>
  post<Template>("/idp/config/templates", body);

export const apiUpdateTemplate = (id: string, body: TemplateUpdateRequest) =>
  put<Template>(`/idp/config/templates/${id}`, body);

export const apiSetDefaultTemplate = (id: string) =>
  post<Template>(`/idp/config/templates/${id}/set-default`);

export const apiDeleteTemplate = (id: string) =>
  delete_<void>(`/idp/config/templates/${id}`);

export const apiReprocessDocument = (id: string, templateId?: string | null, documentTypeId?: string | null) => {
  const params = new URLSearchParams();
  if (templateId) params.append("template_id", templateId);
  if (documentTypeId) params.append("document_type_id", documentTypeId);
  const query = params.toString();
  return post<Document>(`/documents/${id}/reprocess${query ? `?${query}` : ""}`);
};

// ---- Tags (Phase 4) -------------------------------------------------------

export type TagCreateInput = {
  name: string;
  color?: string;
  match?: string;
  matchingAlgorithm?: string;
  isInsensitive?: boolean;
  isInboxTag?: boolean;
};

export const apiTags = () => get<Tag[]>("/tags");
export const apiCreateTag = (data: TagCreateInput) => post<Tag>("/tags", data);
export const apiPatchTag = (id: string, data: Partial<TagCreateInput>) =>
  patch_<Tag>(`/tags/${id}`, data);
export const apiDeleteTag = (id: string) => delete_<void>(`/tags/${id}`);

export const apiAssignTag = (docId: string, tagId: string) =>
  post<void>(`/documents/${docId}/tags/${tagId}`);
export const apiUnassignTag = (docId: string, tagId: string) =>
  delete_<void>(`/documents/${docId}/tags/${tagId}`);

export interface ApplyRulesResponse {
  processed: number;
  total: number;
  hasMore: boolean;
}

/** Retroactively applies tag/correspondent match rules to existing documents,
 * one page at a time. Caller loops on hasMore. */
export const apiApplyRules = (page: number = 1) =>
  post<ApplyRulesResponse>(`/tags/apply-rules?page=${page}`);

// ---- Correspondents (Phase 4) --------------------------------------------

export type CorrespondentCreateInput = {
  name: string;
  email?: string | null;
  match?: string;
  matchingAlgorithm?: string;
  isInsensitive?: boolean;
};

export const apiCorrespondents = () => get<Correspondent[]>("/correspondents");
export const apiCreateCorrespondent = (data: CorrespondentCreateInput) =>
  post<Correspondent>("/correspondents", data);
export const apiPatchCorrespondent = (
  id: string,
  data: Partial<CorrespondentCreateInput>
) => patch_<Correspondent>(`/correspondents/${id}`, data);
export const apiDeleteCorrespondent = (id: string) =>
  delete_<void>(`/correspondents/${id}`);

// ---- Custom Fields (Phase 5) ---------------------------------------------

export type CustomFieldCreateInput = {
  name: string;
  fieldType: string;
  options?: string[];
  position?: number;
};

export const apiCustomFields = () => get<CustomField[]>("/custom-fields");
export const apiCreateCustomField = (data: CustomFieldCreateInput) =>
  post<CustomField>("/custom-fields", data);
export const apiPatchCustomField = (id: string, data: Partial<CustomFieldCreateInput>) =>
  patch_<CustomField>(`/custom-fields/${id}`, data);
export const apiDeleteCustomField = (id: string) => delete_<void>(`/custom-fields/${id}`);

export const apiSetFieldValue = (docId: string, fieldId: string, value: unknown) =>
  post<FieldValue>(`/documents/${docId}/fields/${fieldId}`, { value });
export const apiDeleteFieldValue = (docId: string, fieldId: string) =>
  delete_<void>(`/documents/${docId}/fields/${fieldId}`);

// ---- Predefined fields per document type (Level 6) -----------------------

export const apiPredefinedFields = () =>
  get<Record<string, PredefinedField[]>>("/document-type-fields");
export const apiAddPredefinedField = (
  documentType: string,
  data: { fieldId: string; required?: boolean; position?: number }
) => post<PredefinedField>(`/document-types/${documentType}/fields`, data);
export const apiPatchPredefinedField = (
  documentType: string,
  fieldId: string,
  data: { required?: boolean; position?: number }
) => patch_<PredefinedField>(`/document-types/${documentType}/fields/${fieldId}`, data);
export const apiRemovePredefinedField = (documentType: string, fieldId: string) =>
  delete_<void>(`/document-types/${documentType}/fields/${fieldId}`);

// ---- Saved Views (Phase 6) -----------------------------------------------

export type SavedViewCreateInput = {
  name: string;
  filterState: Record<string, unknown>;
  isDefault?: boolean;
};

export const apiSavedViews = () => get<SavedView[]>("/saved-views");
export const apiCreateSavedView = (data: SavedViewCreateInput) =>
  post<SavedView>("/saved-views", data);
export const apiPatchSavedView = (
  id: string,
  data: Partial<SavedViewCreateInput>
) => patch_<SavedView>(`/saved-views/${id}`, data);
export const apiDeleteSavedView = (id: string) =>
  delete_<void>(`/saved-views/${id}`);

// ---- Bulk operations (Phase 6) -------------------------------------------

export const apiBulkTrash = (documentIds: string[]) =>
  post<{ updated: number }>("/documents/bulk-trash", { documentIds });

export const apiBulkTag = (
  documentIds: string[],
  tagId: string,
  action: "assign" | "remove"
) => post<{ updated: number }>("/documents/bulk-tag", { documentIds, tagId, action });

export const apiBulkSetType = (documentIds: string[], documentType: string) =>
  post<{ updated: number }>("/documents/bulk-set-type", { documentIds, documentType });

// ---- Export (Level 3) ------------------------------------------------------

function triggerBrowserDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Fetches a binary response with the auth header attached (fetch, not <a href>,
 * since download endpoints require Authorization) and triggers a browser
 * save-as. Filename comes from Content-Disposition when the server sets one. */
async function downloadFile(
  path: string,
  opts: { method?: string; body?: unknown; fallbackName: string }
): Promise<{ truncated: boolean }> {
  const headers = await authHeaders();
  const res = await fetch(`${getBaseUrl()}${path}`, {
    method: opts.method ?? "GET",
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) throw new Error(`${opts.method ?? "GET"} ${path} → ${res.status} ${await res.text()}`);
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition");
  const filename = disposition?.match(/filename="([^"]+)"/)?.[1] ?? opts.fallbackName;
  const truncated = res.headers.get("X-Export-Truncated") === "true";
  triggerBrowserDownload(blob, filename);
  return { truncated };
}

/** Exports the current filtered document set as CSV or XLSX. Reuses the same
 * filter shape as apiDocuments so "export what I'm looking at" is exact. */
export const apiExportDocuments = (
  query: DocumentsQuery,
  format: "csv" | "xlsx"
) => {
  const params = new URLSearchParams(
    Object.fromEntries(
      Object.entries({ ...query, format })
        .filter(([, v]) => v !== undefined)
        .map(([k, v]) => [k, String(v)])
    )
  ).toString();
  return downloadFile(`/documents/export?${params}`, { fallbackName: `documents.${format}` });
};

export const apiBulkDownload = (documentIds: string[]) =>
  downloadFile("/documents/bulk-download", {
    method: "POST",
    body: { documentIds },
    fallbackName: "documents.zip",
  });

// ---- Shares (Level 3) ------------------------------------------------------

export interface DocumentShare {
  id: string;
  documentId: string;
  token: string;
  createdAt: string;
  expiresAt: string;
}

export const apiCreateShare = (documentId: string, expiresInDays: number) =>
  post<DocumentShare>(`/documents/${documentId}/share`, { expiresInDays });

export const apiListShares = (documentId: string) =>
  get<DocumentShare[]>(`/documents/${documentId}/shares`);

export const apiRevokeShare = (shareId: string) => delete_<void>(`/shares/${shareId}`);

export interface ResolvedShare {
  url: string;
  filename: string;
  mimeType: string;
}

/** Public — resolves a share token to a signed download URL. No auth header;
 * the token itself is the authorization. Used by the public /shared/[token]
 * page, which has no logged-in session. */
export async function apiResolveShare(token: string): Promise<ResolvedShare> {
  const res = await fetch(`${getBaseUrl()}/share/${token}`);
  if (!res.ok) {
    let detail = await res.text();
    try {
      detail = (JSON.parse(detail).detail as string) ?? detail;
    } catch {
      /* non-JSON body — keep raw text */
    }
    throw new Error(detail || `Failed to resolve link (${res.status})`);
  }
  return res.json() as Promise<ResolvedShare>;
}

// ---------------------------------------------------------------------------
// Spreadsheet Center — Export API
// ---------------------------------------------------------------------------

export interface ExportDocumentType {
  name: string;
  count: number;
}

export interface ExportTemplate {
  id: string;
  name: string;
  documentType: string;
}

export interface ExportMeta {
  documentTypes: ExportDocumentType[];
  templates: ExportTemplate[];
}

export interface ExportFilters {
  documentType?: string;
  templateId?: string;
  status?: string;
  dateFrom?: string; // YYYY-MM-DD
  dateTo?: string;   // YYYY-MM-DD
}

export interface SpreadsheetPreviewResponse {
  rows: Record<string, unknown>[];
  total: number;
}

/** Fetch doc types and templates for the Spreadsheet Center filter dropdowns. */
export async function fetchExportMeta(): Promise<ExportMeta> {
  return get<ExportMeta>("/export/meta");
}

/** Fetch available canonical column names for the current filter selection. */
export async function fetchExportFields(filters: ExportFilters): Promise<string[]> {
  return post<string[]>("/export/fields", filters);
}

/** Fetch a preview of the spreadsheet rows (JSON, max reasonable limit). */
export async function fetchExportPreview(
  filters: ExportFilters,
  columns: string[],
  mode: "summary" | "expanded"
): Promise<SpreadsheetPreviewResponse> {
  return post<SpreadsheetPreviewResponse>("/export/spreadsheet?format=preview", {
    ...filters,
    columns,
    mode,
  });
}

/** Trigger a CSV download via the browser. */
export async function downloadExportCsv(
  filters: ExportFilters,
  columns: string[],
  mode: "summary" | "expanded"
): Promise<void> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new Error("Not authenticated");

  const res = await fetch(`${getBaseUrl()}/export/spreadsheet?format=csv`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },

    body: JSON.stringify({ ...filters, columns, mode }),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Export failed: ${res.status} ${text}`);
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `export_${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
