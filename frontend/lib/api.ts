/**
 * Typed API client for the DataWiz backend.
 *
 * Attaches the Supabase access token as a Bearer header on every request.
 * All methods return camelCase objects matching the types in types/index.ts.
 */

import { supabase } from "@/lib/supabase";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api";

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

// ---- Auth ----
export const apiBootstrap = () => post<{ user: unknown; tenant: unknown }>("/auth/bootstrap");
export const apiMe = () => get<{ user: unknown; tenant: unknown }>("/auth/me");

// ---- Dashboard ----
export const apiDashboard = () => get<unknown>("/dashboard");

// ---- Documents ----
export type DocumentsQuery = {
  status?: string;
  type?: string;
  sort?: string;
  q?: string;
  page?: number;
};
export const apiDocuments = (query: DocumentsQuery = {}) => {
  const params = new URLSearchParams(
    Object.fromEntries(Object.entries(query).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)]))
  ).toString();
  return get<unknown>(`/documents${params ? `?${params}` : ""}`);
};
export const apiDocument = (id: string) => get<unknown>(`/documents/${id}`);
export const apiUploadDocument = (form: FormData) => postForm<unknown>("/documents", form);
export const apiRetryDocument = (id: string) => post<unknown>(`/documents/${id}/retry`);

// ---- Search ----
export type SearchQuery = { q: string; type?: string; date?: string };
export const apiSearch = (query: SearchQuery) => {
  const params = new URLSearchParams(
    Object.fromEntries(Object.entries(query).filter(([, v]) => v) as [string, string][])
  ).toString();
  return get<unknown>(`/search?${params}`);
};

// ---- Settings ----
export const apiOrganisation = () => get<unknown>("/settings/organisation");
export const apiUsers = () => get<unknown>("/settings/users");
export const apiApiKeys = () => get<unknown>("/settings/api-keys");
