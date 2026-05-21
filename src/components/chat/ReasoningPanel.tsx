import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, ChevronRight, Info } from "lucide-react";
import { cn } from "@/lib/cn";
import type { ReasoningEntry } from "@/store";

const SOURCE_LABEL_KEYS: Record<string, string> = {
  risk_profiler: "reasoning.sources.riskProfiler",
  market_data: "reasoning.sources.marketData",
  portfolio: "reasoning.sources.portfolio",
  budget: "reasoning.sources.budget",
  news: "reasoning.sources.news",
  memory: "reasoning.sources.memory",
  user_input: "reasoning.sources.userInput",
} as const;

const AGENT_LABEL_KEYS: Record<string, string> = {
  advisor: "reasoning.agents.advisor",
  risk_profiler: "reasoning.agents.riskProfiler",
} as const;

function labelSource(source: string, t: ReturnType<typeof useTranslation<"chat">>["t"]): string {
  const key = SOURCE_LABEL_KEYS[source];
  return key ? t(key as never) : source.replace(/_/g, " ");
}

function labelAgent(agent: string, t: ReturnType<typeof useTranslation<"chat">>["t"]): string {
  const key = AGENT_LABEL_KEYS[agent];
  return key ? t(key as never) : agent;
}

function DriverChip({ source, factor, impact }: { source: string; factor: string; impact: string }) {
  const { t } = useTranslation("chat");
  return (
    <div className="rounded-md border border-line bg-surface px-2 py-1.5 text-[11px] leading-snug">
      <div className="flex items-center gap-1.5">
        <span className="rounded bg-accent-muted/40 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-accent">
          {labelSource(source, t)}
        </span>
      </div>
      <p className="mt-1 text-content">{factor}</p>
      {impact && (
        <p className="mt-0.5 text-[10px] italic text-content-muted">→ {impact}</p>
      )}
    </div>
  );
}

function ReasoningCard({ entry }: { entry: ReasoningEntry }) {
  const { t } = useTranslation("chat");
  const [open, setOpen] = useState(false);
  const hasKey = entry.key_drivers && entry.key_drivers.length > 0;
  const hasAlloc =
    entry.allocation_drivers &&
    entry.allocation_drivers.some((a) => a.drivers && a.drivers.length > 0);
  const hasDetail = hasKey || hasAlloc;

  return (
    <div className="rounded-lg border border-line bg-surface-raised">
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
          <p className="text-[11px] font-medium text-content">
            {t("reasoning.why")}{" "}
            <span className="text-[10px] font-normal text-content-muted">
              · {labelAgent(entry.agent, t)}
            </span>
          </p>
          {entry.why_summary && (
            <p className="mt-0.5 text-[11px] leading-snug text-content-muted">
              {entry.why_summary}
            </p>
          )}
          {entry.agent === "risk_profiler" &&
            (entry.risk_score !== undefined || entry.profile) && (
              <p className="mt-1 text-[10px] text-content-muted">
                {entry.risk_score !== undefined && <>{t("reasoning.score")}: <span className="font-semibold text-content">{entry.risk_score}/125</span> · </>}
                {entry.profile && <>{t("reasoning.style")}: <span className="font-semibold text-content">{entry.profile}</span></>}
                {entry.equity_band && entry.equity_band[0] !== undefined && (
                  <> · {t("reasoning.equityRange")}: <span className="tabular-nums">{entry.equity_band[0]}-{entry.equity_band[1]}%</span></>
                )}
              </p>
            )}
        </div>
        {hasDetail && (
          <span className="shrink-0 text-content-muted">
            {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          </span>
        )}
      </button>

      {open && hasDetail && (
        <div className="space-y-3 border-t border-line px-3 py-3">
          {hasKey && (
            <div>
              <p className="mb-1.5 text-[9px] uppercase tracking-widest text-content-muted">
                {t("reasoning.keyFactors")}
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
              <p className="text-[9px] uppercase tracking-widest text-content-muted">
                {t("reasoning.allocationRationale")}
              </p>
              {entry.allocation_drivers
                .filter((a) => a.drivers && a.drivers.length > 0)
                .map((a) => (
                  <div key={a.asset_class}>
                    <p className="mb-1 text-[10px] font-medium text-content">
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
    <div className="mt-3 space-y-2 border-t border-line pt-3">
      {entries.map((e) => (
        <ReasoningCard key={e.agent} entry={e} />
      ))}
    </div>
  );
}
