import { useState } from "react";
import { ChevronDown, ChevronRight, Info } from "lucide-react";
import { cn } from "@/lib/cn";
import type { ReasoningEntry } from "@/store";

const SOURCE_LABELS: Record<string, string> = {
  risk_profiler: "Risk profilin",
  market_data: "Piyasa verisi",
  portfolio: "Portföyün",
  budget: "Bütçen",
  news: "Haberler",
  memory: "Geçmiş konuşmalar",
  user_input: "Senin tercihin",
};

const AGENT_LABELS: Record<string, string> = {
  advisor: "Yatırım Komitesi",
  risk_profiler: "Risk Yöneticisi",
};

function labelSource(source: string): string {
  return SOURCE_LABELS[source] ?? source.replace(/_/g, " ");
}

function labelAgent(agent: string): string {
  return AGENT_LABELS[agent] ?? agent;
}

function DriverChip({ source, factor, impact }: { source: string; factor: string; impact: string }) {
  return (
    <div className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--surface))] px-2 py-1.5 text-[11px] leading-snug">
      <div className="flex items-center gap-1.5">
        <span className="rounded bg-accent-muted/40 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-accent">
          {labelSource(source)}
        </span>
      </div>
      <p className="mt-1 text-[hsl(var(--text-primary))]">{factor}</p>
      {impact && (
        <p className="mt-0.5 text-[10px] italic text-[hsl(var(--text-muted))]">→ {impact}</p>
      )}
    </div>
  );
}

function ReasoningCard({ entry }: { entry: ReasoningEntry }) {
  const [open, setOpen] = useState(false);
  const hasKey = entry.key_drivers && entry.key_drivers.length > 0;
  const hasAlloc =
    entry.allocation_drivers &&
    entry.allocation_drivers.some((a) => a.drivers && a.drivers.length > 0);
  const hasDetail = hasKey || hasAlloc;

  return (
    <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={!hasDetail}
        className={cn(
          "flex w-full items-start gap-2 px-3 py-2 text-left transition-colors",
          hasDetail && "hover:bg-white/5"
        )}
      >
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />
        <div className="flex-1 min-w-0">
          <p className="text-[11px] font-medium text-[hsl(var(--text-primary))]">
            Neden bu öneri?{" "}
            <span className="text-[10px] font-normal text-[hsl(var(--text-muted))]">
              · {labelAgent(entry.agent)}
            </span>
          </p>
          {entry.why_summary && (
            <p className="mt-0.5 text-[11px] leading-snug text-[hsl(var(--text-muted))]">
              {entry.why_summary}
            </p>
          )}
          {entry.agent === "risk_profiler" &&
            (entry.risk_score !== undefined || entry.profile) && (
              <p className="mt-1 text-[10px] text-[hsl(var(--text-muted))]">
                {entry.risk_score !== undefined && <>Skor: <span className="font-semibold text-[hsl(var(--text-primary))]">{entry.risk_score}/125</span> · </>}
                {entry.profile && <>Profil: <span className="font-semibold text-[hsl(var(--text-primary))]">{entry.profile}</span></>}
                {entry.equity_band && entry.equity_band[0] !== undefined && (
                  <> · Hisse bandı: <span className="tabular-nums">{entry.equity_band[0]}-{entry.equity_band[1]}%</span></>
                )}
              </p>
            )}
        </div>
        {hasDetail && (
          <span className="shrink-0 text-[hsl(var(--text-muted))]">
            {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          </span>
        )}
      </button>

      {open && hasDetail && (
        <div className="space-y-3 border-t border-[hsl(var(--border))] px-3 py-3">
          {hasKey && (
            <div>
              <p className="mb-1.5 text-[9px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
                Anahtar faktörler
              </p>
              <div className="grid gap-1.5 sm:grid-cols-2">
                {entry.key_drivers.map((d, i) => (
                  <DriverChip key={`k-${i}`} {...d} />
                ))}
              </div>
            </div>
          )}
          {hasAlloc && entry.allocation_drivers && (
            <div className="space-y-2">
              <p className="text-[9px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
                Sınıf bazında gerekçeler
              </p>
              {entry.allocation_drivers
                .filter((a) => a.drivers && a.drivers.length > 0)
                .map((a) => (
                  <div key={a.asset_class}>
                    <p className="mb-1 text-[10px] font-medium text-[hsl(var(--text-primary))]">
                      {a.asset_class}
                    </p>
                    <div className="grid gap-1.5 sm:grid-cols-2">
                      {a.drivers.map((d, i) => (
                        <DriverChip key={`${a.asset_class}-${i}`} {...d} />
                      ))}
                    </div>
                  </div>
                ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function ReasoningPanel({ entries }: { entries: ReasoningEntry[] }) {
  if (!entries || entries.length === 0) return null;
  return (
    <div className="mt-3 space-y-2 border-t border-[hsl(var(--border))] pt-3">
      {entries.map((e) => (
        <ReasoningCard key={e.agent} entry={e} />
      ))}
    </div>
  );
}
