import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { AgentTrace } from "./AgentTrace";
import type { ToolActivity } from "@/store";

describe("AgentTrace", () => {
  it("expands the step trace and renders a calc card from a tool result", () => {
    const steps: ToolActivity[] = [
      {
        runId: "r1",
        tool: "compute_concentration",
        args: { top_n: 5 },
        status: "done",
        result: JSON.stringify({
          ok: true,
          ui_type: "bars",
          formatted_value: "HHI 0.31 (moderately concentrated)",
          formula: "HHI = Σ(weightᵢ)²",
          data: { bars: [{ label: "NVDA", value: 42 }] },
        }),
      },
    ];

    render(<AgentTrace steps={steps} label="Steps" />);

    // Collapsed by default → expand the trace.
    fireEvent.click(screen.getByText(/Steps \(1\)/));
    // The step chip is labelled by its tool name → expand it.
    fireEvent.click(screen.getByText("compute_concentration"));

    // The full chain (parseToolResult → isCalcEnvelope → CalcResultCard) renders.
    expect(screen.getByText(/HHI 0\.31/)).toBeTruthy();
    expect(screen.getByText("NVDA")).toBeTruthy();
  });

  it("renders nothing when there are no steps", () => {
    const { container } = render(<AgentTrace steps={[]} label="Steps" />);
    expect(container.firstChild).toBeNull();
  });
});
