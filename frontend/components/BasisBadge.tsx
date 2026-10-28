import { Badge } from "@/components/ui/badge";

export type CostBasis = "estimated" | "reported" | "billed" | "unavailable" | "simulated" | "mixed";

const BASIS: Record<
  CostBasis,
  { label: string; title: string; variant: "default" | "secondary" | "outline" | "destructive" }
> = {
  billed: { label: "Billed", title: "Taken from a provider invoice", variant: "default" },
  reported: { label: "Reported", title: "Cost reported by the provider or client", variant: "secondary" },
  estimated: { label: "Estimated", title: "Computed from token usage and the pricing catalogue", variant: "outline" },
  mixed: { label: "Mixed", title: "Combines estimated and reported costs", variant: "outline" },
  simulated: { label: "Simulated", title: "Demo prices, not a real provider price list", variant: "outline" },
  unavailable: { label: "Unavailable", title: "No pricing or usage data to compute a cost", variant: "destructive" },
};

export function BasisBadge({ basis }: { basis: CostBasis }) {
  const { label, title, variant } = BASIS[basis];
  return (
    <Badge variant={variant} title={title}>
      {label}
    </Badge>
  );
}
