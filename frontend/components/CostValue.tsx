"use client";

import { BasisBadge, type CostBasis } from "@/components/BasisBadge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";

type CostValueProps = {
  value: number | null;
  currency: string | null;
  basis?: CostBasis;
  className?: string;
};

export function CostValue({ value, currency, basis, className }: CostValueProps) {
  return (
    <span className={cn("inline-flex items-center gap-2 tabular-nums", className)}>
      {value === null ? (
        <Tooltip>
          <TooltipTrigger className="cursor-help text-muted-foreground underline decoration-dotted underline-offset-4">
            Unknown
          </TooltipTrigger>
          <TooltipContent>No pricing or usage data for some events</TooltipContent>
        </Tooltip>
      ) : (
        <span>{formatMoney(value, currency)}</span>
      )}
      {basis ? <BasisBadge basis={basis} /> : null}
    </span>
  );
}
