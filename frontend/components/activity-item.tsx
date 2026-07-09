"use client";

/**
 * Shared rendering for a single ActivityEvent — icon + human-readable label.
 * Used by the Dashboard's recent-activity widget, Settings > Activity (org-wide
 * audit trail), and the document detail page's History tab. Covers every
 * ACT_* type from backend/app/models/activity_event.py — extend both together.
 */

import {
  Upload,
  CheckCircle2,
  AlertCircle,
  ArrowUpRight,
  FileText,
  Pencil,
  Trash2,
  RotateCcw,
  XCircle,
  Search,
  UserPlus,
} from "lucide-react";
import type { ActivityEvent } from "@/types";

export function ActivityIcon({ type }: { type: ActivityEvent["type"] }) {
  switch (type) {
    case "upload":
      return <Upload className="w-3.5 h-3.5 text-blue-600" />;
    case "processing_complete":
      return <CheckCircle2 className="w-3.5 h-3.5 text-green-600" />;
    case "processing_failed":
      return <AlertCircle className="w-3.5 h-3.5 text-red-500" />;
    case "download":
      return <ArrowUpRight className="w-3.5 h-3.5 text-slate-500" />;
    case "edit":
      return <Pencil className="w-3.5 h-3.5 text-amber-600" />;
    case "trash":
      return <Trash2 className="w-3.5 h-3.5 text-red-500" />;
    case "restore":
      return <RotateCcw className="w-3.5 h-3.5 text-green-600" />;
    case "permanent_delete":
      return <XCircle className="w-3.5 h-3.5 text-red-600" />;
    case "search":
      return <Search className="w-3.5 h-3.5 text-slate-500" />;
    case "user_added":
      return <UserPlus className="w-3.5 h-3.5 text-blue-600" />;
    default:
      return <FileText className="w-3.5 h-3.5 text-slate-400" />;
  }
}

export function ActivityLabel({ event }: { event: ActivityEvent }) {
  const doc = <span className="font-medium text-slate-800">{event.documentName}</span>;
  switch (event.type) {
    case "upload":
      return <>uploaded {doc}</>;
    case "processing_complete":
      return <>{doc} processed</>;
    case "processing_failed":
      return <>{doc} failed{event.meta ? ` — ${event.meta}` : ""}</>;
    case "download":
      return <>downloaded {doc}</>;
    case "edit":
      return <>edited {doc}{event.meta ? ` — ${event.meta}` : ""}</>;
    case "trash":
      return <>moved {doc} to trash</>;
    case "restore":
      return <>restored {doc} from trash</>;
    case "permanent_delete":
      return <>permanently deleted {doc}</>;
    case "search":
      return <>searched{event.meta ? ` — "${event.meta}"` : ""}</>;
    case "user_added":
      return <>added a new user{event.meta ? ` — ${event.meta}` : ""}</>;
    default:
      return <>{event.type}</>;
  }
}
