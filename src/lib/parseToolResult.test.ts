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
});
