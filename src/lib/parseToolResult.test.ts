import { describe, expect, it } from "vitest";
import { parseToolResult } from "./parseToolResult";

describe("parseToolResult", () => {
  it("parses escaped JSON inside a ToolMessage repr", () => {
    const raw =
      "content='{\\\"scan_time\\\": \\\"2026-05-13T22:29:36.810413+00:00\\\", \\\"top_trending\\\": [{\\\"symbol\\\": \\\"PENGU\\\", \\\"mentions\\\": 3}]}'";

    expect(parseToolResult(raw)).toEqual({
      scan_time: "2026-05-13T22:29:36.810413+00:00",
      top_trending: [{ symbol: "PENGU", mentions: 3 }],
    });
  });

  it("keeps parsing when the whole ToolMessage repr is JSON encoded", () => {
    const raw = JSON.stringify(
      "content='{\\\"scan_time\\\": \\\"2026-05-13T22:29:36.810413+00:00\\\", \\\"top_trending\\\": []}' name='scan_hot_trends'"
    );

    expect(parseToolResult(raw)).toEqual({
      scan_time: "2026-05-13T22:29:36.810413+00:00",
      top_trending: [],
    });
  });

  it("parses a full-size quant envelope", () => {
    const env = {
      ok: true,
      ui_type: "equity_curve",
      formatted_value: "+42.5% vs +31.0% buy & hold",
      data: { equity: [1, 1.1, 1.25], benchmark: [1, 1.05, 1.2], drawdown: [0, -1.2, 0] },
    };
    expect(parseToolResult(JSON.stringify(env))).toEqual(env);
  });

  it("degrades a TRUNCATED envelope to the raw string, not a throw", () => {
    // backend/app/main.py:_summarize_tool_output cuts every tool result at 4000
    // chars. A payload over that arrives as invalid JSON. This pins the current
    // contract: parsing must not throw — it hands back the string, and
    // CitationChip renders it as plain text instead of a card.
    // app/tools/quant_tools.py caps curves at 80 points to stay under the limit;
    // if that cap ever regresses, the failure looks like a missing chart, not an
    // error, which is why this behaviour is worth pinning.
    const truncated = '{"ok": true, "ui_type": "equity_curve", "data": {"equity": [1.0, 1.1, 1.2';
    const parsed = parseToolResult(truncated);
    expect(typeof parsed).toBe("string");
    expect(parsed).toBe(truncated);
  });
});
