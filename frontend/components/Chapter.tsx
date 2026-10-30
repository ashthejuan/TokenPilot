import type { ReactNode } from "react";

import {
  CHAPTER,
  CHAPTER_DESCRIPTION,
  CHAPTER_TITLE,
} from "@/lib/layout";
import { cn } from "@/lib/utils";

export function Chapter({
  title,
  description,
  children,
  className,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn(CHAPTER, className)}>
      <div>
        <h2 className={CHAPTER_TITLE}>{title}</h2>
        {description ? <p className={CHAPTER_DESCRIPTION}>{description}</p> : null}
      </div>
      {children}
    </section>
  );
}
