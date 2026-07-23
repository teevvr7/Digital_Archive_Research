/** Shared formatting utilities. No mock data or fixed dates. */

export function formatBytes(bytes: number): string {
  if (bytes >= 1_073_741_824) return `${(bytes / 1_073_741_824).toFixed(1)} GB`;
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`;
  if (bytes >= 1_024) return `${(bytes / 1_024).toFixed(0)} KB`;
  return `${bytes} B`;
}

export function formatRelativeTime(isoString: string): string {
  const diffMs = Date.now() - new Date(isoString).getTime();
  const diffMins = Math.floor(diffMs / 60_000);
  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${Math.floor(diffHours / 24)}d ago`;
}

/**
 * Days remaining before a trashed document is auto-purged, given when it was
 * trashed and the tenant's effective retention window. Floored, never
 * negative — a document past its window still shows 0 (auto-retention is
 * opportunistic, not instant, so it can briefly still be visible after
 * "0 days left" until the next check runs).
 */
export function daysUntilTrashPurge(deletedAtIso: string, retentionDays: number): number {
  const daysSinceDeleted = (Date.now() - new Date(deletedAtIso).getTime()) / 86_400_000;
  return Math.max(0, Math.ceil(retentionDays - daysSinceDeleted));
}
