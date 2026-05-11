/**
 * Live multi-agent visualization.
 *
 * Renders the supervisor + 7 specialists as a ReactFlow graph. Nodes
 * react to ``useAgentVizStore`` events emitted by the chat SSE pipeline:
 *   agent_start → status="running" + pulse animation + animated edge
 *   agent_done  → status="done"   + edge static
 *   reset on chat done → all back to "idle"
 *
 * Layout is fixed (no auto-layout): supervisor on top, 7 workers in
 * two rows below. Pan / zoom / drag are disabled — this is a passive
 * visualization, not an interactive flow editor.
 */
import { useMemo } from "react";
import ReactFlow, {
  Background, BackgroundVariant, type Edge, type Node,
} from "reactflow";
import "reactflow/dist/style.css";

import { useAgentVizStore } from "@/store";
import { AgentNode, type AgentNodeData, type AgentStatus } from "./AgentNode";

const NODE_TYPES = { agent: AgentNode };

interface AgentMeta {
  position: { x: number; y: number };
  label: string;
  icon: AgentNodeData["icon"];
  isSupervisor?: boolean;
}

// Two-row hub-and-spoke. Supervisor centered on top, 4 + 3 below.
const AGENTS: Record<string, AgentMeta> = {
  supervisor:      { position: { x: 220, y: 0 },   label: "Supervisor",   icon: "GitBranch", isSupervisor: true },
  market_data:     { position: { x: -20, y: 110 }, label: "Market Data",  icon: "TrendingUp" },
  portfolio:       { position: { x: 130, y: 110 }, label: "Portfolio",    icon: "Briefcase" },
  budget_coach:    { position: { x: 270, y: 110 }, label: "Budget",       icon: "Wallet" },
  news_sentiment:  { position: { x: 410, y: 110 }, label: "News",         icon: "Newspaper" },
  risk_profiler:   { position: { x: 60,  y: 200 }, label: "Risk",         icon: "Shield" },
  memory:          { position: { x: 200, y: 200 }, label: "Memory",       icon: "Database" },
  document_parser: { position: { x: 340, y: 200 }, label: "Documents",    icon: "FileText" },
};

export function AgentGraph() {
  const events = useAgentVizStore((s) => s.events);

  const nodes: Node<AgentNodeData>[] = useMemo(
    () =>
      Object.entries(AGENTS).map(([id, meta]) => {
        const status: AgentStatus = (events[id]?.status as AgentStatus) ?? "idle";
        return {
          id,
          type: "agent",
          position: meta.position,
          draggable: false,
          selectable: false,
          data: {
            label: meta.label,
            icon: meta.icon,
            status,
            isSupervisor: meta.isSupervisor,
          },
        };
      }),
    [events]
  );

  const edges: Edge[] = useMemo(
    () =>
      Object.keys(AGENTS)
        .filter((id) => id !== "supervisor")
        .map((id) => {
          const status = events[id]?.status;
          const running = status === "running";
          const done = status === "done";
          return {
            id: `e-supervisor-${id}`,
            source: "supervisor",
            target: id,
            animated: running,
            style: {
              stroke: running ? "#1FB57A" : done ? "rgba(31,181,122,0.35)" : "rgba(255,255,255,0.08)",
              strokeWidth: running ? 1.6 : 1,
            },
          };
        }),
    [events]
  );

  return (
    <div className="card-muted flex h-[320px] flex-col p-2">
      <div className="min-h-0 flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          fitView
          fitViewOptions={{ padding: 0.25 }}
          proOptions={{ hideAttribution: true }}
          // Display-only: kill all the editor affordances
          panOnDrag={false}
          panOnScroll={false}
          zoomOnScroll={false}
          zoomOnPinch={false}
          zoomOnDoubleClick={false}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          preventScrolling={false}
        >
          <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="rgba(255,255,255,0.04)" />
        </ReactFlow>
      </div>
      <div className="mt-2 flex items-center justify-between px-1 text-[10px] text-[hsl(var(--text-muted))]">
        <span>Live agent activity</span>
        <span className="flex gap-3">
          <Legend color="bg-[hsl(var(--text-muted))]" label="idle" />
          <Legend color="bg-accent" label="running" />
          <Legend color="bg-accent/40" label="done" />
        </span>
      </div>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className={`inline-block h-1.5 w-1.5 rounded-full ${color}`} />
      {label}
    </span>
  );
}
