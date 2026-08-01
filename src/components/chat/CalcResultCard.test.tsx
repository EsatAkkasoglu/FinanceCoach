import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CalcResultCard, isCalcEnvelope } from "./CalcResultCard";

describe("isCalcEnvelope", () => {
  it("accepts success and error envelopes", () => {
    expect(isCalcEnvelope({ ok: true, ui_type: "metric" })).toBe(true);
    expect(isCalcEnvelope({ ok: false, error: "bad" })).toBe(true);
    expect(isCalcEnvelope({ ok: true, formatted_value: "$1" })).toBe(true);
  });
  it("rejects non-envelopes", () => {
    expect(isCalcEnvelope(null)).toBe(false);
    expect(isCalcEnvelope([1, 2, 3])).toBe(false);
    expect(isCalcEnvelope({ ticker: "AAPL", price: 100 })).toBe(false);
  });
});

describe("CalcResultCard", () => {
  it("renders a metric envelope verbatim with its formula", () => {
    render(
      <CalcResultCard
        env={{
          ok: true,
          ui_type: "metric",
          raw_value: 8333.33,
          formatted_value: "$8,333",
          formula: "PMT(rate=0.000000/mo, nper=12, pv=0, fv=100000)",
          data: { required_monthly: 8333.33 },
        }}
      />
    );
    expect(screen.getByText("$8,333")).toBeTruthy();
    expect(screen.getByText(/PMT\(/)).toBeTruthy();
  });

  it("renders allocation bars", () => {
    render(
      <CalcResultCard
        env={{
          ok: true,
          ui_type: "bars",
          formatted_value: "$10,000",
          data: { bars: [{ label: "stock", value: 60 }, { label: "bond", value: 40 }] },
        }}
      />
    );
    expect(screen.getByText("stock")).toBeTruthy();
    expect(screen.getByText("60.0%")).toBeTruthy();
  });

  it("renders a diverging drift bar", () => {
    render(
      <CalcResultCard
        env={{
          ok: true,
          ui_type: "diverging_bar",
          data: { bars: [{ label: "stock", value: 5 }, { label: "cash", value: -5 }] },
        }}
      />
    );
    expect(screen.getByText(/stock \+5\.0%/)).toBeTruthy();
  });

  it("renders a metrics table", () => {
    render(
      <CalcResultCard
        env={{
          ok: true,
          ui_type: "table",
          data: { rows: [{ metric: "Sharpe ratio", value: 1.2, unit: "" }] },
        }}
      />
    );
    expect(screen.getByText("Sharpe ratio")).toBeTruthy();
  });

  it("renders an error envelope without crashing", () => {
    render(<CalcResultCard env={{ ok: false, error: "months must be >= 1" }} />);
    expect(screen.getByText(/Couldn't compute/)).toBeTruthy();
    expect(screen.getByText(/months must be/)).toBeTruthy();
  });
});

// ── quant ui_types (backend/app/quant) ──────────────────────────────────────
// Recharts needs a measurable container; happy-dom reports 0×0 for
// ResponsiveContainer, so these assert the surrounding chrome and the
// no-crash contract rather than SVG internals.

describe("CalcResultCard — equity_curve", () => {
  const env = {
    ok: true,
    ui_type: "equity_curve" as const,
    raw_value: 42.5,
    formatted_value: "+42.5% vs +31.0% buy & hold",
    data: {
      ticker: "SPY",
      strategy: "sma_cross",
      start_date: "2021-03-01",
      end_date: "2024-02-29",
      equity: [1, 1.1, 1.25, 1.425],
      benchmark: [1, 1.05, 1.2, 1.31],
      drawdown: [0, -1.2, 0, -3.4],
      metrics: { n_bars: 750 },
    },
  };

  it("shows the headline and both endpoint dates", () => {
    render(<CalcResultCard env={env} />);
    expect(screen.getByText("+42.5% vs +31.0% buy & hold")).toBeTruthy();
    expect(screen.getByText("2021-03-01")).toBeTruthy();
    expect(screen.getByText("2024-02-29")).toBeTruthy();
  });

  it("renders nothing rather than crashing on a truncated curve", () => {
    const { container } = render(
      <CalcResultCard env={{ ...env, data: { ...env.data, equity: [1] } }} />
    );
    expect(container).toBeTruthy();
  });
});

describe("CalcResultCard — frontier", () => {
  it("renders the legend and the target weight bars", () => {
    render(
      <CalcResultCard
        env={{
          ok: true,
          ui_type: "frontier",
          formatted_value: "Sharpe 1.42 (current 1.10)",
          data: {
            points: [
              { vol_pct: 8, return_pct: 4 },
              { vol_pct: 12, return_pct: 9 },
              { vol_pct: 18, return_pct: 12 },
            ],
            current: { vol_pct: 15, return_pct: 7, label: "Current" },
            optimal: { vol_pct: 12, return_pct: 9, label: "max sharpe" },
            bars: [{ label: "VOO", value: 62.5 }, { label: "BND", value: 37.5 }],
          },
        }}
      />
    );
    expect(screen.getByText("Sharpe 1.42 (current 1.10)")).toBeTruthy();
    expect(screen.getByText("frontier")).toBeTruthy();
    expect(screen.getByText("optimal")).toBeTruthy();
    // The weight bars reuse BarsView, so the allocation is still readable.
    expect(screen.getByText("VOO")).toBeTruthy();
    expect(screen.getByText("62.5%")).toBeTruthy();
  });
});

describe("CalcResultCard — heatmap", () => {
  it("renders a labelled correlation matrix", () => {
    render(
      <CalcResultCard
        env={{
          ok: true,
          ui_type: "heatmap",
          data: {
            labels: ["AAPL", "MSFT"],
            matrix: [
              [1, 0.72],
              [0.72, 1],
            ],
          },
        }}
      />
    );
    expect(screen.getAllByText("AAPL").length).toBeGreaterThan(0);
    expect(screen.getAllByText("0.72").length).toBe(2);
  });

  it("skips rendering when the matrix is empty", () => {
    const { container } = render(
      <CalcResultCard env={{ ok: true, ui_type: "heatmap", data: { labels: [], matrix: [] } }} />
    );
    expect(container.querySelector("table")).toBeNull();
  });
});
