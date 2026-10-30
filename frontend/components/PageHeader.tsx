import type { ReactNode } from "react";

import {
  PAGE_DESCRIPTION,
  PAGE_HEADER,
  PAGE_TITLE,
} from "@/lib/layout";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className={PAGE_HEADER}>
      <div className="min-w-0">
        <h1 className={PAGE_TITLE}>{title}</h1>
        {description ? <p className={PAGE_DESCRIPTION}>{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
