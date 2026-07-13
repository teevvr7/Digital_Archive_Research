/**
 * Typed API client for the DataWiz backend.
 *
 * Attaches the Supabase access token as a Bearer header on every request.
 * All methods return camelCase objects matching the backend CamelModel schemas.
 */

import { supabase } from "@/lib/supabase";
import type { Correspondent, CustomField, Document, ActivityEvent, FieldValue, SavedView, SearchListResponse, Tag } from "@/types";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api";

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
  const res = await fetch(`${BASE}${path}`, { headers: await authHeaders() });
  if (!res.ok) throw new Error(`GET ${path} → ${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const headers = await authHeaders();
  const res = await fetch(`${BASE}${path}`, {
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

async function patch_<T>(path: string, body?: unknown): Promise<T> {
  const headers = await authHeaders();
  const res = await fetch(`${BASE}${path}`, {
    method: "PATCH",
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`PATCH ${path} → ${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

async function delete_<T>(path: string): Promise<T> {
  const headers = await authHeaders();
  const res = await fetch(`${BASE}${path}`, { method: "DELETE", headers });
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
  const res = await fetch(`${BASE}${path}`, {
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
  const res = await fetch(`${BASE}/auth/signup`, {
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

/** Returns a short-lived signed URL; open it in a new tab to trigger download. */
export const apiDownloadUrl = (id: string) =>
  get<{ url: string }>(`/documents/${id}/download`);

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

/** Rename the organisation. Admin-only (backend enforces via require_admin). */
export const apiUpdateTenant = (name: string) =>
  patch_<AuthTenant>("/auth/tenant", { name });

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
  const res = await fetch(`${BASE}${path}`, {
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
  const res = await fetch(`${BASE}/share/${token}`);
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
