/**
 * Parse a raw tool result string into a usable value.
 *
 * Handles these formats (in order):
 *   1. Direct JSON object/array:  `{"ticker": "F", ...}`
 *   2. JSON-encoded string (may be truncated):  `"content='...' name='...'"`
 *   3. LangChain ToolMessage repr:  `content='...' name='...' tool_call_id='...'`
 *
 * Returns the parsed value (object/array/string) or null if input is empty.
 */
export function parseToolResult(raw: string): unknown {
  if (!raw) return null;
  const s = raw.trim();

  // 1. Starts with { or [ → direct JSON object/array
  if (s[0] === "{" || s[0] === "[") {
    try { return JSON.parse(s); } catch { /* fall through */ }
  }

  // 2. Starts with " → JSON-encoded string (possibly truncated)
  if (s[0] === '"') {
    let inner: string;
    try {
      const v = JSON.parse(s);           // complete JSON string
      if (typeof v !== "string") return v;
      inner = v;
    } catch {
      inner = s.slice(1);                // truncated — strip leading " and continue
    }
    return parseToolResult(inner);       // recurse with the unwrapped content
  }

  // 3. LangChain ToolMessage repr: content='...' name='...'
  if (s.startsWith("content=")) {
    const m =
      s.match(/^content='([\s\S]*?)'\s+name=/s) ??
      s.match(/^content="([\s\S]*?)"\s+name=/s) ??
      s.match(/^content='([\s\S]*)'/s);
    if (m) return parseJsonContent(m[1]);
  }

  return s;
}

/** Try to parse a string as JSON, with a fallback that unescapes Python-style `\"`. */
function parseJsonContent(s: string): unknown {
  // Direct JSON
  try { return JSON.parse(s); } catch { /* fall through */ }

  // Python repr emits `{\"key\": \"val\"}` — unescape and retry
  if (s.includes('\\"')) {
    const unescaped = s.replace(/\\"/g, '"').replace(/\\\\/g, "\\");
    try { return JSON.parse(unescaped); } catch { /* fall through */ }
  }

  return s;
}
