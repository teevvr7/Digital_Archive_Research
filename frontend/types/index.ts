export interface SavedView {
  id: string;
  name: string;
  filterState: Record<string, unknown>;
  isDefault: boolean;
  createdAt: string;
}

export interface CustomField {
  id: string;
  name: string;
  fieldType: string; // text | number | date | boolean | select
  options: string[];
  position: number;
  createdAt: string;
}

export interface FieldValue {
  fieldId: string;
  fieldName: string;
  fieldType: string;
  value: unknown;
}

/** A custom field predefined for a document type (Level 6 — Metadata). */
export interface PredefinedField {
  id: string;
  documentType: string;
  fieldId: string;
  fieldName: string;
  fieldType: string; // text | number | date | boolean | select
  options: string[];
  required: boolean;
  position: number;
}

export interface Tag {
  id: string;
  tenantId: string;
  name: string;
  color: string;
  match: string;
  matchingAlgorithm: string;
  isInsensitive: boolean;
  isInboxTag: boolean;
  createdAt: string;
}

export interface Correspondent {
  id: string;
  tenantId: string;
  name: string;
  email: string | null;
  match: string;
  matchingAlgorithm: string;
  isInsensitive: boolean;
  createdAt: string;
}

export type ProcessingStatus =
  | "queued"
  | "extracting_text"
  | "ocr_processing"
  | "ai_extraction"
  | "completed"
  | "needs_review"
  | "failed";

export type DocumentType =
  | "invoice"
  | "receipt"
  | "contract"
  | "report"
  | "letter"
  | "form"
  | "other";

export type UserRole = "admin" | "user";

export interface Tenant {
  id: string;
  name: string;
  plan: "starter" | "professional" | "enterprise";
  storageUsedBytes: number;
  storageLimitBytes: number;
  documentsCount: number;
  createdAt: string;
}

export interface User {
  id: string;
  email: string;
  name: string;
  role: UserRole;
  avatarInitials: string;
  tenantId: string;
  createdAt: string;
  lastLoginAt: string;
}

export interface Document {
  id: string;
  tenantId: string;
  filename: string;
  originalFilename: string;
  title: string;
  documentType: DocumentType;
  mimeType: string;
  sizeBytes: number;
  status: ProcessingStatus;
  uploadedBy: string;
  uploadedAt: string;
  processedAt: string | null;
  documentDate: string | null;
  pageCount: number | null;
  hasTextLayer: boolean;
  ocrConfidence: number | null;
  confidence: number | null;
  extractedData: Record<string, unknown> | null;
  extractedText: string | null;
  tags: { id: string; name: string; color: string }[];
  correspondent: { id: string; name: string } | null;
  customFieldValues: FieldValue[];
  storageKey: string;
  hasThumbnail: boolean;
  deletedAt: string | null;
  duplicateOfDocumentId: string | null;
}

export interface ActivityEvent {
  id: string;
  type:
    | "upload"
    | "processing_complete"
    | "processing_failed"
    | "search"
    | "download"
    | "user_added"
    | "edit"
    | "trash"
    | "restore"
    | "permanent_delete"
    | "duplicate_detected"
    | "user_removed"
    | "role_changed";
  documentId?: string;
  documentName?: string;
  userId: string;
  userName: string;
  timestamp: string;
  meta?: string;
}

export interface SearchResult {
  document: Document;
  score: number;
  /** Server-rendered HTML snippet with <mark> highlights (from ts_headline). */
  snippet?: string;
  /** Which fields matched: any of "content", "filename". */
  matchedFields: string[];
}

export interface SearchListResponse {
  items: SearchResult[];
  total: number;
  page: number;
  pageSize: number;
}
