import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  savingsBadgeKind,
  savingsBadgeLabel,
  type SavingsInput,
} from "@/lib/benchmarks";
import { cn } from "@/lib/utils";

const KIND_CLASS: Record<string, string> = {
  potential: "border-border bg-muted text-muted-foreground",
  measured: "border-transparent bg-blue-500/15 text-blue-800 dark:text-blue-200",
  verified: "border-transparent bg-green-600 text-white dark:bg-green-600",
  not_optimization: "border-transparent bg-amber-500/15 text-amber-800 dark:text-amber-200",
  inconclusive: "border-border bg-muted text-muted-foreground",
};

export function SavingsBadge({
  status,
  correctness_preserved,
  cost_delta,
  reasons = [],
}: SavingsInput & { reasons?: string[] }) {
  const input: SavingsInput = { status, correctness_preserved, cost_delta };
  const badge = (
    <Badge variant="outline" className={cn(KIND_CLASS[savingsBadgeKind(input)])}>
      {savingsBadgeLabel(input)}
    </Badge>
  );
  if (savingsBadgeKind(input) !== "inconclusive" || reasons.length === 0) {
    return badge;
  }
  return (
    <Tooltip>
      <TooltipTrigger className="cursor-help">
        {badge}
      </TooltipTrigger>
      <TooltipContent>
        <ul className="max-w-64 list-disc space-y-1 pl-4 text-left">
          {reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      </TooltipContent>
    </Tooltip>
  );
}
