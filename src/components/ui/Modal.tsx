import { useEffect, type ReactNode } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/cn";

interface Props {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg";
  closeOnBackdrop?: boolean;
}

const SIZES = {
  sm: "max-w-md",
  md: "max-w-xl",
  lg: "max-w-3xl",
};

export function Modal({
  open, onClose, title, description, children, footer,
  size = "md", closeOnBackdrop = true,
}: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm animate-in fade-in"
      onClick={() => closeOnBackdrop && onClose()}
      role="dialog"
      aria-modal="true"
    >
      <div
        className={cn(
          "relative w-full overflow-hidden rounded-2xl border border-line bg-surface shadow-2xl",
          SIZES[size]
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-4 border-b border-line px-6 py-4">
          <div className="min-w-0">
            <h2 className="text-base font-semibold tracking-tight">{title}</h2>
            {description && (
              <p className="mt-0.5 text-xs text-content-muted">{description}</p>
            )}
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="-mr-2 -mt-1 rounded-lg p-1.5 text-content-muted transition hover:bg-surface-raised hover:text-content"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="max-h-[70vh] overflow-y-auto px-6 py-5">{children}</div>

        {footer && (
          <footer className="flex items-center justify-end gap-2 border-t border-line bg-surface-raised/40 px-6 py-3">
            {footer}
          </footer>
        )}
      </div>
    </div>
  );
}
