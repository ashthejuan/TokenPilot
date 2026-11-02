import { Button } from "@/components/ui/button";
import { canGoNext, canGoPrev } from "@/lib/pagination";

type ListPaginationProps = {
  pageIndex: number;
  nextCursor: string | null;
  loading: boolean;
  onPrev: () => void;
  onNext: () => void;
};

export function ListPagination({
  pageIndex,
  nextCursor,
  loading,
  onPrev,
  onNext,
}: ListPaginationProps) {
  const prevEnabled = canGoPrev(pageIndex);
  const nextEnabled = canGoNext(nextCursor);
  if (!prevEnabled && !nextEnabled) return null;

  return (
    <div className="flex items-center gap-3">
      <Button variant="outline" size="sm" onClick={onPrev} disabled={!prevEnabled || loading}>
        Previous
      </Button>
      <span className="text-sm tabular-nums text-muted-foreground">Page {pageIndex + 1}</span>
      <Button variant="outline" size="sm" onClick={onNext} disabled={!nextEnabled || loading}>
        Next
      </Button>
    </div>
  );
}
