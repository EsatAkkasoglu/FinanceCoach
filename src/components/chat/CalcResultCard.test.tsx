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
