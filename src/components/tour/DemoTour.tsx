import { useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { ChevronLeft, ChevronRight, X, Map } from "lucide-react";
import { useTourStore, TOUR_STEPS } from "@/store";
import { buildLocalizedPath, getLanguageFromPath, stripLanguagePrefix } from "@/lib/routing";
import { cn } from "@/lib/cn";

export function DemoTour() {
  const { active, step, next, prev, skip } = useTourStore();
  const navigate = useNavigate();
  const location = useLocation();
  const lang = getLanguageFromPath(location.pathname) ?? "tr";
  const current = TOUR_STEPS[step];

  // Auto-navigate when step changes
  useEffect(() => {
    if (!active) return;
    const target = current.path;
    const appPath = stripLanguagePrefix(location.pathname);
    if (!appPath.startsWith(target)) {
      navigate(buildLocalizedPath(lang, target), { replace: false });
    }
  }, [active, step]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!active) return null;

  const isFirst = step === 0;
  const isLast = step === TOUR_STEPS.length - 1;

  return (
    <>
      {/* Subtle backdrop */}
      <div className="pointer-events-none fixed inset-0 z-40 bg-black/20" />

      {/* Tour card */}
      <div className="fixed bottom-6 right-6 z-50 w-80 rounded-2xl border border-line bg-surface shadow-2xl">
        {/* Header */}
        <div className="flex items-center gap-2 rounded-t-2xl bg-accent/10 px-4 py-3">
          <Map className="h-4 w-4 shrink-0 text-accent" />
          <span className="flex-1 text-xs font-semibold uppercase tracking-widest text-accent">
            Tur — {step + 1} / {TOUR_STEPS.length}
          </span>
          <button
            onClick={skip}
            className="rounded-md p-0.5 text-content-muted transition hover:text-content"
            title="Turu kapat"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>

        {/* Body */}
        <div className="px-4 py-4">
          <h3 className="mb-2 text-sm font-semibold text-content">{current.title}</h3>
          <p className="text-xs leading-relaxed text-content-muted">{current.body}</p>
        </div>

        {/* Progress dots */}
        <div className="flex justify-center gap-1.5 pb-1">
          {TOUR_STEPS.map((_, i) => (
            <div
              key={i}
              className={cn(
                "h-1.5 rounded-full transition-all",
                i === step ? "w-4 bg-accent" : "w-1.5 bg-default"
              )}
            />
          ))}
        </div>

        {/* Navigation */}
        <div className="flex items-center justify-between px-4 pb-4 pt-3">
          <button
            onClick={prev}
            disabled={isFirst}
            className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs text-content-muted transition hover:bg-surface-raised hover:text-content disabled:opacity-30"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            Geri
          </button>

          <button
            onClick={skip}
            className="text-[10px] text-content-muted underline underline-offset-2 transition hover:text-content"
          >
            Turu atla
          </button>

          <button
            onClick={next}
            className="flex items-center gap-1 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white transition hover:bg-accent/90"
          >
            {isLast ? "Tamamla" : "İleri"}
            {!isLast && <ChevronRight className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>
    </>
  );
}

/** Floating "?" button to replay the tour */
export function TourReplayButton() {
  const { seen, active, start } = useTourStore();
  if (!seen && !active) return null;
  if (active) return null;
  return (
    <button
      onClick={start}
      title="Turu tekrar başlat"
      className="flex h-8 w-8 items-center justify-center rounded-full border border-line bg-surface-raised text-[10px] font-bold text-content-muted shadow transition hover:border-accent hover:text-accent"
    >
      ?
    </button>
  );
}
