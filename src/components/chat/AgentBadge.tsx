import {
  TrendingUp, Briefcase, Wallet, Newspaper, Shield, Database, FileText, GitBranch,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/cn";

const META: Record<string, { labelKey: string; icon: LucideIcon }> = {
  supervisor: { labelKey: "agents.supervisor", icon: GitBranch },
  market_data: { labelKey: "agents.marketData", icon: TrendingUp },
  portfolio: { labelKey: "agents.portfolio", icon: Briefcase },
  budget_coach: { labelKey: "agents.budgetCoach", icon: Wallet },
  news_sentiment: { labelKey: "agents.newsSentiment", icon: Newspaper },
  risk_profiler: { labelKey: "agents.riskProfiler", icon: Shield },
  memory: { labelKey: "agents.memory", icon: Database },
  document_parser: { labelKey: "agents.documents", icon: FileText },
} as const;

export function AgentBadge({ name, className }: { name: string; className?: string }) {
  const { t } = useTranslation("chat");
  const known = META[name];
  const m = known ?? { labelKey: name, icon: GitBranch };
  const Icon = m.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-accent/40 bg-accent-muted/40 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-accent",
        className
      )}
    >
      <Icon className="h-3 w-3" />
      {known ? t(known.labelKey as never) : name}
    </span>
  );
}
