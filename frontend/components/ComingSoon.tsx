import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function ComingSoon({ title, phase }: { title: string; phase: number }) {
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <Card>
        <CardHeader>
          <CardTitle>Coming in Phase {phase}</CardTitle>
        </CardHeader>
        <CardContent className="text-muted-foreground">
          This page is not built yet. The Overview shows recorded usage and cost today.
        </CardContent>
      </Card>
    </div>
  );
}
