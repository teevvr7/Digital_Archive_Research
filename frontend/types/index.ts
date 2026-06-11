export type ProcessingStatus =
  | "queued"
  | "extracting_text"
  | "ocr_processing"
  | "ai_extraction"
  | "completed"
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
  documentType: DocumentType;
  mimeType: string;
  sizeBytes: number;
  status: ProcessingStatus;
  uploadedBy: string;
  uploadedAt: string;
  processedAt: string | null;
  pageCount: number | null;
  hasTextLayer: boolean;
  ocrConfidence: number | null;
  extractedData: Record<string, unknown> | null;
  extractedText: string | null;
  tags: string[];
  storageKey: string;
}

export interface ActivityEvent {
  id: string;
  type:
    | "upload"
    | "processing_complete"
    | "processing_failed"
    | "search"
    | "download"
    | "user_added";
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
