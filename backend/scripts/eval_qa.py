"""Live Q&A evaluation harness for the FinCoach assistant.

Walks a curated pool of realistic user questions (grouped by module, with
both simple and complex variants) against the running backend, captures the
SSE event stream for each turn, and writes a Markdown report summarising:

  - which specialist(s) ran
  - which tools were invoked (with arg/result preview)
  - the final assistant reply
  - basic timing

Usage:
    # backend running on :8765 in another terminal
    cd backend
    uv run python scripts/eval_qa.py

Outputs ``reports/qa_eval_<utc-iso>.md`` (path printed at end).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx


BACKEND_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = BACKEND_DIR / "reports"

DEFAULT_BASE_URL = "http://localhost:8765"
DEFAULT_USERNAME = "testUser"
DEFAULT_PASSWORD = "TestUser123!"
DEFAULT_DISPLAY_CURRENCY = "TRY"


# Question pool: 6 modules × 2 (simple + complex), all read-only so the
# user's state is never mutated by the eval run.
QUESTION_POOL: list[tuple[str, str, str]] = [
    # (module, difficulty, question)
    ("Portfolio", "simple",
     "Portföyümde şu an neler var, toplam değer nedir?"),
    ("Portfolio", "complex",
     "Portföyümün varlık sınıfı bazında dağılımını ve risk profilime göre "
     "konsantrasyon riskini analiz et."),

    ("Market Data", "simple",
     "NVDA hissesinin güncel fiyatı ve günlük değişimi nedir?"),
    ("Market Data", "complex",
     "NVDA için 8 boyutlu temel + teknik analizi yap, AL/SAT/TUT önerin nedir?"),

    ("TEFAS Funds", "simple",
     "GTL fonunun güncel fiyatı ve fon adı nedir?"),
    ("TEFAS Funds", "complex",
     "Risk profilime uygun en iyi performans gösteren 3 altın fonu ile "
     "3 para piyasası fonunu karşılaştır."),

    ("News & Sentiment", "simple",
     "Tesla ile ilgili son haberler neler?"),
    ("News & Sentiment", "complex",
     "NVDA ile ilgili son bir haftadaki haberlerin genel sentiment'i pozitif "
     "mi negatif mi, ve bu portföyümdeki teknoloji ağırlığını nasıl etkiler?"),

    ("Budget", "simple",
     "Bu ayki toplam harcamam ve gelirim ne kadar?"),
    ("Budget", "complex",
     "Son 30 günde hangi kategoride en çok harcama yapmışım, bu kategoriyi "
     "azaltırsam aylık ne kadar tasarruf ederim?"),

    ("Synthesis / Goals", "simple",
     "Ev alma hedefime ulaşmam için aylık ne kadar biriktirmem gerek?"),
    ("Synthesis / Goals", "complex",
     "Mevcut portföyüm, harcama alışkanlıklarım ve risk profilim göz "
     "önüne alındığında en yakın hedefime kaç ayda ulaşırım, hangi "
     "değişiklikleri önerirsin?"),
]


@dataclass
class TurnResult:
    module: str
    difficulty: str
    question: str
    final_answer: str = ""
    final_agent: str = ""
    specialists: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    duration_s: float = 0.0
    error: str | None = None


def login(base_url: str, username: str, password: str) -> str:
    r = httpx.post(
        f"{base_url}/auth/login",
        json={"username": username, "password": password},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["token"]


def create_conversation(client: httpx.Client, base_url: str) -> tuple[str, str]:
    r = client.post(f"{base_url}/conversations", json={}, timeout=10)
    r.raise_for_status()
    body = r.json()
    return body["id"], body["thread_id"]


def _iter_sse(stream) -> "Iterable[tuple[str, dict]]":  # noqa: F821
    """Yield (event_name, data_dict) pairs from an open httpx streaming response.

    SSE frames are terminated by a blank line. We read line-by-line via
    ``iter_lines()`` (which decodes UTF-8 and strips the trailing newline)
    and flush whenever we see an empty line.
    """
    event_name = "message"
    data_lines: list[str] = []
    for line in stream.iter_lines():
        if line == "":
            if data_lines:
                payload = "\n".join(data_lines)
                try:
                    data = json.loads(payload)
                except Exception:
                    data = {"_raw": payload}
                yield event_name, data
            event_name = "message"
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        try:
            data = json.loads("\n".join(data_lines))
        except Exception:
            data = {"_raw": "\n".join(data_lines)}
        yield event_name, data


def run_turn(
    headers: dict,
    base_url: str,
    module: str,
    difficulty: str,
    question: str,
    display_currency: str,
) -> TurnResult:
    res = TurnResult(module=module, difficulty=difficulty, question=question)
    started = time.time()
    # Fresh client per turn — sharing a connection pool across long streaming
    # /chat requests caused premature end-of-stream when httpx reused a closed
    # connection from a prior turn.
    client = httpx.Client(headers=headers, timeout=httpx.Timeout(30.0))
    try:
        conv_id, thread_id = create_conversation(client, base_url)
    except Exception as exc:
        res.error = f"create_conversation failed: {exc}"
        res.duration_s = time.time() - started
        client.close()
        return res

    tokens: list[str] = []
    pending_tools: dict[str, dict] = {}

    try:
        with client.stream(
            "POST",
            f"{base_url}/chat",
            json={
                "message": question,
                "thread_id": thread_id,
                "conv_id": conv_id,
                "display_currency": display_currency,
            },
            timeout=httpx.Timeout(180.0, read=180.0),
        ) as stream:
            stream.raise_for_status()
            for name, data in _iter_sse(stream):
                if name == "agent_start":
                    agent = data.get("agent") or ""
                    if agent and agent not in res.specialists:
                        res.specialists.append(agent)
                    if not data.get("internal", False):
                        res.final_agent = agent
                elif name == "tool_call":
                    run_id = data.get("run_id") or str(uuid.uuid4())
                    pending_tools[run_id] = {
                        "tool": data.get("tool"),
                        "args": data.get("args") or {},
                        "result": None,
                    }
                elif name == "tool_result":
                    run_id = data.get("run_id") or ""
                    if run_id in pending_tools:
                        pending_tools[run_id]["result"] = data.get("result")
                elif name == "token":
                    tokens.append(str(data.get("text") or ""))
                elif name == "agent_message":
                    content = data.get("content") or ""
                    if content and not tokens:
                        tokens.append(content)
                elif name in ("error", "agent_error"):
                    res.error = (
                        f"{name}: {data.get('message') or data.get('type') or 'unknown'}"
                    )
                elif name == "done":
                    break
    except httpx.HTTPError as exc:
        res.error = f"http error: {exc}"
    except Exception as exc:  # noqa: BLE001
        res.error = f"stream error: {exc}"
    finally:
        client.close()

    res.final_answer = "".join(tokens).strip()
    res.tool_calls = list(pending_tools.values())
    res.duration_s = time.time() - started
    return res


def _truncate(text: str, n: int = 400) -> str:
    text = text.strip()
    if len(text) <= n:
        return text
    return text[: n - 1].rstrip() + "…"


def write_report(results: list[TurnResult], out_path: Path, base_url: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# FinCoach Q&A Evaluation Report")
    lines.append("")
    lines.append(f"- Generated: `{datetime.utcnow().isoformat(timespec='seconds')}Z`")
    lines.append(f"- Backend: `{base_url}`")
    lines.append(f"- Total questions: {len(results)}")
    ok = sum(1 for r in results if not r.error and r.final_answer)
    lines.append(f"- Successful: **{ok}/{len(results)}**")
    total_dur = sum(r.duration_s for r in results)
    lines.append(f"- Total wall time: {total_dur:.1f}s")
    lines.append("")
    lines.append("## Summary table")
    lines.append("")
    lines.append("| # | Module | Difficulty | Final agent | Tools | Duration | Status |")
    lines.append("|---|--------|-----------|-------------|-------|----------|--------|")
    for i, r in enumerate(results, 1):
        status = "❌ " + r.error if r.error else ("✅" if r.final_answer else "⚠️ empty")
        tools = ", ".join(sorted({(t.get("tool") or "?") for t in r.tool_calls})) or "—"
        lines.append(
            f"| {i} | {r.module} | {r.difficulty} | "
            f"{r.final_agent or '—'} | {tools} | {r.duration_s:.1f}s | {status} |"
        )
    lines.append("")

    lines.append("## Per-turn detail")
    for i, r in enumerate(results, 1):
        lines.append("")
        lines.append(f"### {i}. {r.module} — {r.difficulty}")
        lines.append("")
        lines.append(f"**Question:** {r.question}")
        lines.append("")
        if r.specialists:
            lines.append(f"**Agents consulted:** {', '.join(r.specialists)}  ")
        if r.final_agent:
            lines.append(f"**Final agent:** `{r.final_agent}`  ")
        lines.append(f"**Duration:** {r.duration_s:.2f}s")
        lines.append("")
        if r.tool_calls:
            lines.append("**Tool calls:**")
            lines.append("")
            for t in r.tool_calls:
                args_preview = _truncate(json.dumps(t.get("args") or {}, ensure_ascii=False), 200)
                result_preview = _truncate(str(t.get("result") or ""), 300)
                lines.append(f"- `{t.get('tool')}`")
                lines.append(f"    - args: `{args_preview}`")
                lines.append(f"    - result: `{result_preview}`")
            lines.append("")
        if r.error:
            lines.append(f"**Error:** `{r.error}`")
            lines.append("")
        lines.append("**Answer:**")
        lines.append("")
        if r.final_answer:
            lines.append("```")
            lines.append(_truncate(r.final_answer, 2000))
            lines.append("```")
        else:
            lines.append("_(no final answer produced)_")
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run FinCoach Q&A eval suite.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--currency", default=DEFAULT_DISPLAY_CURRENCY)
    parser.add_argument("--out", default=None,
                        help="Override output path (default: reports/qa_eval_<ts>.md)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Run only the first N questions (0 = all)")
    args = parser.parse_args()

    print(f"→ Logging in as {args.username}…")
    token = login(args.base_url, args.username, args.password)
    headers = {"Authorization": f"Bearer {token}"}

    pool = QUESTION_POOL[: args.limit] if args.limit > 0 else QUESTION_POOL
    print(f"→ Running {len(pool)} questions against {args.base_url}")

    results: list[TurnResult] = []
    for i, (module, difficulty, q) in enumerate(pool, 1):
        print(f"  [{i:2}/{len(pool)}] {module} · {difficulty} … ", end="", flush=True)
        r = run_turn(headers, args.base_url, module, difficulty, q, args.currency)
        results.append(r)
        tag = "OK" if r.final_answer and not r.error else (r.error or "empty")
        print(f"{r.duration_s:5.1f}s  [{tag[:60]}]")

    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(args.out) if args.out else REPORTS_DIR / f"qa_eval_{ts}.md"
    write_report(results, out_path, args.base_url)
    print(f"\n✓ Report written: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
