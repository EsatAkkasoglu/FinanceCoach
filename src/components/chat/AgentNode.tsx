import { Handle, Position } from "reactflow";
import { motion } from "framer-motion";
import {
  GitBranch, TrendingUp, Briefcase, Wallet, Newspaper, Shield, Database, FileText,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/cn";

export type AgentStatus = "idle" | "running" | "done" | "error";

const ICONS: Record<string, LucideIcon> = {
  GitBranch,
  TrendingUp,
  Briefcase,
  Wallet,
  Newspaper,
  Shield,
  Database,
  FileText,
};

export interface AgentNodeData {
  label: string;
  icon: keyof typeof ICONS;
  status: AgentStatus;
  isSupervisor?: boolean;
}

const STATUS_STYLES: Record<AgentStatus, string> = {
  idle: "border-[hsl(var(--border))] bg-[hsl(var(--surface))] text-[hsl(var(--text-muted))]",
  running: "border-accent bg-accent-muted text-accent shadow-glow",
  done: "border-accent/40 bg-[hsl(var(--surface))] text-[hsl(var(--text))]",
  error: "border-loss bg-[hsl(var(--surface))] text-loss",
};

export function AgentNode({ data }: { data: AgentNodeData }) {
  const Icon = ICONS[data.icon] ?? GitBranch;
  const isRunning = data.status === "running";

  return (
    <>
      {/* Hidden but required by ReactFlow for edges to attach */}
      <Handle type="target" position={Position.Top} className="!h-0.5 !w-0.5 !border-0 !bg-transparent" />
      <motion.div
        animate={
          isRunning
            ? { scale: [1, 1.06, 1] }
            : { scale: 1 }
        }
        transition={{
          duration: 1.4,
          repeat: isRunning ? Infinity : 0,
          ease: "easeInOut",
        }}
        className={cn(
          "flex items-center gap-2 rounded-lg border-2 px-3 py-2 text-xs font-medium transition-colors",
          STATUS_STYLES[data.status],
          data.isSupervisor && "px-4 py-2.5 text-sm"
        )}
      >
        <Icon className={cn("h-3.5 w-3.5 shrink-0", data.isSupervisor && "h-4 w-4")} />
        <span className="whitespace-nowrap">{data.label}</span>
      </motion.div>
      <Handle type="source" position={Position.Bottom} className="!h-0.5 !w-0.5 !border-0 !bg-transparent" />
    </>
  );
}
