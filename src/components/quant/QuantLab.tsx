/**
 * Quant Lab — the page surface over backend/app/quant.
 *
 * The chat tools answer quant questions inline but must downsample to fit the
 * SSE payload cap; this page hits /quant/* directly and gets the full-resolution
 * series, every walk-forward fold, and the whole frontier.
 *
 * Motion is reduced-motion gated (the panels pass `isAnimationActive={!reduce}`
 * to every recharts series) and the standing disclaimer is part of the page
 * chrome, not something a panel can forget to render.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { motion, useReducedMotion } from "framer-motion";
import { FlaskConical, Info } from "lucide-react";
import { BacktestPanel } from "./BacktestPanel";
import { FrontierPanel } from "./FrontierPanel";
import { RiskPanel } from "./RiskPanel";
import { cn } from "@/lib/cn";

type Tab = "backtest" | "optimize" | "risk";
const TABS: Tab[] = ["backtest", "optimize", "risk"];

export function QuantLab() {
  const { t } = useTranslation("quant");
  const reduce = useReducedMotion();
  const [tab, setTab] = useState<Tab>("backtest");

  const Wrapper = reduce ? "div" : motion.div;
  const wrapperProps = reduce
    ? {}
    : { initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.3 } };

  return (
    <Wrapper {...wrapperProps} className="space-y-4">
      <header>
        <h1 className="flex items-center gap-2 text-xl font-semibold">
          <FlaskConical className="h-5 w-5 text-accent" />
          {t("title")}
        </h1>
        <p className="mt-1 max-w-3xl text-sm text-content-muted">{t("subtitle")}</p>
      </header>

      <nav className="flex gap-1 border-b border-line" role="tablist">
        {TABS.map((key) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-sm font-medium transition",
              tab === key
                ? "border-accent text-content"
                : "border-transparent text-content-muted hover:text-content",
            )}
          >
            {t(`tabs.${key}`)}
          </button>
        ))}
      </nav>

      {tab === "backtest" && <BacktestPanel />}
      {tab === "optimize" && <FrontierPanel />}
      {tab === "risk" && <RiskPanel />}

      <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-content-muted">
        <Info className="mt-0.5 h-3 w-3 shrink-0" />
        {t("disclaimer")}
      </p>
    </Wrapper>
  );
}
