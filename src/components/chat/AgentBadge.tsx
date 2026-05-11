import {
  TrendingUp, Briefcase, Wallet, Newspaper, Shield, Database, FileText, GitBranch,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/cn";

const META: Record<string, { label: string; icon: LucideIcon }> = {
  supervisor: { label: "Supervisor", icon: GitBranch },
  market_data: { label: "Market Data", icon: TrendingUp },
  portfolio: { label: "Portfolio", icon: Briefcase },
  budget_coach: { label: "Budget Coach", icon: Wallet },
  news_sentiment: { label: "News & Sentiment", icon: Newspaper },
  risk_profiler: { label: "Risk Profiler", icon: Shield },
  memory: { label: "Memory", icon: Database },
  document_parser: { label: "Documents", icon: FileText },
};

export function AgentBadge({ name, className }: { name: string; className?: string }) {
  const m = META[name] ?? { label: name, icon: GitBranch };
  const Icon = m.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-accent/40 bg-accent-muted/40 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-accent",
        className
      )}
    >
      <Icon className="h-3 w-3" />
      {m.label}
    </span>
  );
}
