/**
 * Collapsible "what I did" trace under an assistant reply. Lists every tool the
 * desks called this turn (already captured in ChatPanel as ToolActivity[]),
 * reusing CitationChip so each step expands to its result — including the rich
 * CalcResultCard for deterministic calc tools. Makes the chat followable:
 * the user can see which numbers came from which tool.
 */
import { useState } from "react";
import { ChevronDown, ListChecks } from "lucide-react";
import { cn } from "@/lib/cn";
import { CitationChip } from "./CitationChip";
import type { ToolActivity } from "@/store";

export function AgentTrace({ steps, label }: { steps: ToolActivity[]; label: string }) {
  const [open, setOpen] = useState(false);
  if (!steps || steps.length === 0) return null;

  return (
    <div className="mt-3 border-t border-line pt-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 text-overline uppercase text-content-muted transition hover:text-accent"
      >
        <ListChecks className="h-3 w-3" />
        <span>{label} ({steps.length})</span>
        <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {steps.map((s) => (
            <CitationChip
              key={s.runId}
              citation={{ tool: s.tool, args: s.args, result: s.result }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
