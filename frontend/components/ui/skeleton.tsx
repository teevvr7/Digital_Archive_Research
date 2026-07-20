/** Base shimmer block. Compose with width/height utility classes, e.g. <Skeleton className="h-4 w-24" />. */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-slate-200 ${className}`} />;
}

/** Loading placeholder for the documents table, mirroring its 7-column layout. */
export function TableRowsSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden" data-testid="table-skeleton">
      <div className="divide-y divide-slate-50">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="flex items-center gap-4 px-4 py-3.5">
            <Skeleton className="h-4 w-4 shrink-0" />
            <div className="flex-1 min-w-0 space-y-1.5">
              <Skeleton className="h-3.5 w-2/5" />
              <Skeleton className="h-2.5 w-1/5" />
            </div>
            <Skeleton className="h-5 w-16 shrink-0" />
            <Skeleton className="h-5 w-20 shrink-0" />
            <Skeleton className="h-3 w-16 shrink-0" />
            <Skeleton className="h-3 w-12 shrink-0" />
          </div>
        ))}
      </div>
    </div>
  );
}

/** Loading placeholder for the documents grid, mirroring DocCard's aspect-[4/3] thumbnail shape. */
export function CardGridSkeleton({ cards = 8 }: { cards?: number }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4" data-testid="grid-skeleton">
      {Array.from({ length: cards }).map((_, i) => (
        <div key={i} className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <Skeleton className="aspect-[4/3] rounded-none" />
          <div className="p-3 space-y-2">
            <Skeleton className="h-3.5 w-4/5" />
            <Skeleton className="h-2.5 w-2/5" />
          </div>
        </div>
      ))}
    </div>
  );
}

/** Loading placeholder for the document detail page while the document/preview is fetched. */
export function DetailSkeleton() {
  return (
    <div className="space-y-6" data-testid="detail-skeleton">
      <div className="flex items-center gap-3">
        <Skeleton className="h-8 w-8 rounded-lg" />
        <Skeleton className="h-5 w-64" />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Skeleton className="lg:col-span-2 h-[480px] rounded-xl" />
        <div className="space-y-4">
          <Skeleton className="h-32 rounded-xl" />
          <Skeleton className="h-48 rounded-xl" />
        </div>
      </div>
    </div>
  );
}
