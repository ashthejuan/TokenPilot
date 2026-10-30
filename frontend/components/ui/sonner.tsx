"use client";

import {
  CircleCheckIcon,
  InfoIcon,
  Loader2Icon,
  OctagonXIcon,
  TriangleAlertIcon,
} from "lucide-react";
import { Toaster as Sonner, type ToasterProps } from "sonner";
import type { CSSProperties } from "react";

/** Light Scandinavian toaster — tokens only, no richColors. */
const Toaster = ({ ...props }: ToasterProps) => {
  return (
    <Sonner
      theme="light"
      className="toaster group"
      position="bottom-right"
      closeButton
      icons={{
        success: <CircleCheckIcon className="size-4" />,
        info: <InfoIcon className="size-4" />,
        warning: <TriangleAlertIcon className="size-4" />,
        error: <OctagonXIcon className="size-4" />,
        loading: <Loader2Icon className="size-4 animate-spin" />,
      }}
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
          "--border-radius": "var(--radius)",
        } as CSSProperties
      }
      toastOptions={{
        classNames: {
          toast: "cn-toast !border-border !bg-popover !text-popover-foreground !shadow-none",
          title: "!text-sm !font-medium !text-foreground",
          description: "!text-sm !text-muted-foreground",
          actionButton:
            "!bg-destructive/10 !text-destructive !border-0 !font-medium hover:!bg-destructive/20",
          cancelButton: "!bg-transparent !text-muted-foreground !border !border-border !font-medium",
          closeButton: "!border-border !bg-background !text-muted-foreground",
        },
      }}
      {...props}
    />
  );
};

export { Toaster };
