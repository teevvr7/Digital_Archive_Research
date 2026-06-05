"use client";

import type { ProcessingStatus } from "@/types";

const STATUS_CONFIG: Record<
  ProcessingStatus,
  { label: string; className: string; dot: string }
> = {
  queued: {
    label: "Queued",
    className: "status-queued",
    dot: "bg-slate-400",
  },
  extracting_text: {
    label: "Extracting Text",
    className: "status-extracting",
    dot: "bg-blue-500 animate-pulse",
  },
  ocr_processing: {
    label: "OCR Processing",
    className: "status-ocr",
    dot: "bg-green-500 animate-pulse",
  },
  ai_extraction: {
    label: "AI Extraction",
    className: "status-ai",
    dot: "bg-violet-500 animate-pulse",
  },
  completed: {
    label: "Completed",
    className: "status-completed",
    dot: "bg-green-500",
  },
  failed: {
    label: "Failed",
    className: "status-failed",
    dot: "bg-red-500",
  },
};

export function StatusBadge({ status }: { status: ProcessingStatus }) {
  const config = STATUS_CONFIG[status];
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${config.className}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${config.dot}`} />
      {config.label}
    </span>
  );
}
