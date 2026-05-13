/**
 * Parse a raw tool result string from the SSE stream into a usable value.
 *
 * The backend can send results in two formats:
 *   1. A JSON-encoded string wrapping a LangChain ToolMessage repr:
 *      `"content='{...}' name='tool' tool_call_id='...'"`
 *   2. A plain LangChain ToolMessage repr (no outer quotes):
 *      `content='{...}' name='tool' tool_call_id='...'`
 *   3. Direct JSON: `{...}` or `[...]`
 *
 * Returns the parsed value (object/array/string) or null if input is empty.
 */
export function parseToolResult(raw: string): unknown {
  if (!raw) return null;

  // Step 1: If the whole thing is JSON, unwrap it.
  // If JSON.parse returns a non-string (object/array/number/bool), we're done.
  // If it returns a string, the backend JSON-encoded the result — keep unwrapping.
  let decoded = raw;
  try {
    const result = JSON.parse(raw);
    if (typeof result !== "string") return result;
    decoded = result; // unwrapped one level of JSON encoding
  } catch {
    // not valid JSON at top level, treat as raw string
  }

  // Step 2: Strip LangChain ToolMessage repr: content='...' name='...' tool_call_id='...'
  const m =
    decoded.match(/^content='([\s\S]*?)'\s+name=/s) ??
    decoded.match(/^content="([\s\S]*?)"\s+name=/s) ??
    decoded.match(/^content='([\s\S]*)'/s);

  if (m) {
    const inner = m[1];
    try {
      return JSON.parse(inner);
    } catch {
      return inner;
    }
  }

  return decoded;
}
