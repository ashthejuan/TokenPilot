import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type Severity = "informational" | "low" | "medium" | "high";

const SEVERITY: Record<
  Severity,
  { label: string; className: string }
> = {
  informational: {
    label: "Informational",
    className: "border-border bg-muted text-muted-foreground",
  },
  low: {
    label: "Low",
    className: "border-transparent bg-secondary text-secondary-foreground",
  },
  medium: {
    label: "Medium",
    className: "border-transparent bg-amber-500/15 text-amber-800 dark:text-amber-200",
  },
  high: {
    label: "High",
    className: "border-transparent bg-destructive/10 text-destructive",
  },
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  const { label, className } = SEVERITY[severity];
  return (
    <Badge variant="outline" className={cn(className)}>
      {label}
    </Badge>
  );
}
