/**
 * Typed API client for the DataWiz backend.
 *
 * Attaches the Supabase access token as a Bearer header on every request.
 * All methods return camelCase objects matching the backend CamelModel schemas.
 */

import { supabase } from "@/lib/supabase";
import type { Document, ActivityEvent, SearchListResponse } from "@/types";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8001/api";

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
  return res.json() as Promise<T>;
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
  return res.json() as Promise<T>;
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
};

export const apiPatchDocument = (id: string, patch: DocumentPatch) =>
  patch_<Document>(`/documents/${id}`, patch);

export const apiTrashDocument = (id: string) =>
  delete_<Document>(`/documents/${id}`);

export const apiRestoreDocument = (id: string) =>
  post<Document>(`/documents/${id}/restore`);

export const apiEmptyTrash = () =>
  post<{ deleted: number }>("/documents/empty-trash");

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

// ---- Settings (Milestone E) ----------------------------------------------

export const apiOrganisation = () => get<unknown>("/settings/organisation");
export const apiUsers = () => get<unknown>("/settings/users");
export const apiApiKeys = () => get<unknown>("/settings/api-keys");
