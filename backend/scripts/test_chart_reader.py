"""Test harness for the chart-reading pipeline.

Runs three different extraction strategies against a single PDF (typically a
Telegram "Yayın Notu" with trade-setup charts) and prints their outputs side
by side so we can compare which strategy reads entry / TP / SL correctly.

Usage (from backend/):
    uv run python scripts/test_chart_reader.py "C:/path/to/yayin_notu.pdf"
    uv run python scripts/test_chart_reader.py "C:/path/to/yayin_notu.pdf" --only B
    uv run python scripts/test_chart_reader.py "C:/path/to/yayin_notu.pdf" --asset SOL

Strategies:
  A) Production two-pass pipeline (GeminiDocumentProcessor.extract_profile).
  B) Single-shot multimodal: PDF + role-aware prompt -> JSON list of setups.
  C) Per-page: split PDF into one image per page, ask the model to extract a
     single trade setup from each page. Highest fidelity, costs N calls.

All three use the model configured in settings (GEMINI_VISION_MODEL).
"""
from __future__ import annotations

import argparse
import mimetypes
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Make `app.*` importable when running from backend/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import BaseModel, Field

from app.services.document_processor.base import DocumentSource
from app.services.document_processor.gemini_processor import (
    GeminiDocumentProcessor,
)
from app.settings import settings


# ---------------------------------------------------------------------------
# Shared schema — what we want out of any chart
# ---------------------------------------------------------------------------
class TradeSetup(BaseModel):
    ticker: str = Field(description="Asset symbol exactly as printed (e.g. SOL, BTC, XAU).")
    direction: str = Field(description="long | short | unclear")
    entry: float | None = None
    tp: list[float] = Field(default_factory=list, description="Take-profit levels, ordered.")
    sl: float | None = None
    leverage: str | None = None
    note: str = Field(default="", description="Author's verbatim bullet note.")
    other_levels: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class TradeSetupList(BaseModel):
    setups: list[TradeSetup]


# ---------------------------------------------------------------------------
# Strategy B — single-shot multimodal + JSON schema
# ---------------------------------------------------------------------------
SINGLE_SHOT_PROMPT = """You are reading a Turkish crypto/markets "Yayın Notu" PDF.
Each bullet introduces ONE asset followed by ONE TradingView chart screenshot.

For every asset, extract a TradeSetup with the trader's intent. Use the chart's
COLOR CODING as ground truth:
  - GREEN/TEAL filled rectangle = take-profit zone for a long (or entry zone for a short).
    TOP edge of the green box = TP target; BOTTOM edge = entry price.
  - RED/MAROON filled rectangle below price = stop-loss zone for a long.
    The number labelling its lower edge = SL.
  - For SHORT setups colors invert: red box above price = TP going down, green box = entry/SL above.
  - Cyan/blue arrows show the expected price path — they disambiguate long vs short.
  - Labels like "2X", "3X", "Halit Pozu" = leverage, NOT price levels.
  - Yellow horizontal lines = key S/R, not entry/TP/SL unless the colored box sits on them.
  - The right-axis highlighted price = current price; do not report it as a level.

Rules:
- Read pixels exactly; do not round or paraphrase numbers.
- If the bullet says the asset is "pas" / "bulaşmalık değil" / "devam" with no trade box,
  emit a TradeSetup with direction="unclear" and entry=tp=sl=null. Still include it.
- Note must be the verbatim Turkish bullet text after the ticker.
- Confidence: 0.9+ when both boxes and arrows are unambiguous, <0.5 when guessing.
"""


def run_strategy_b(processor: GeminiDocumentProcessor, source: DocumentSource) -> TradeSetupList:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=processor._api_key)  # noqa: SLF001
    doc_part = types.Part.from_bytes(data=source.data, mime_type=source.mime_type)
    response = client.models.generate_content(
        model=processor._vision_model,  # noqa: SLF001
        contents=[doc_part, SINGLE_SHOT_PROMPT],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=TradeSetupList,
            temperature=0.0,
        ),
    )
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, TradeSetupList):
        return parsed
    return TradeSetupList.model_validate_json(response.text)


# ---------------------------------------------------------------------------
# Strategy C — per-page rendering
# ---------------------------------------------------------------------------
PER_PAGE_PROMPT = """This image is ONE page from a Turkish crypto Yayın Notu PDF.
It typically contains 1-2 trade-setup charts (asset bullet + TradingView screenshot).

Extract every TradeSetup on this page using the color-coded zone semantics:
  - GREEN box above price = TP zone (long). Top edge = TP, bottom edge = entry.
  - RED box below price  = SL zone (long). Bottom edge = SL.
  - Reverse for short.
  - Cyan arrows confirm direction.
  - 2X/3X/"Halit Pozu" = leverage label, not a price.

If the page only contains "pas" / "bulaşmalık değil" / "devam" commentary,
emit setups with direction=unclear and null prices but include the asset.

Numbers must be read pixel-exact (no rounding).
"""


def render_pdf_pages(data: bytes) -> list[tuple[int, bytes]]:
    """Return (page_num, png_bytes) for each page. Requires PyMuPDF."""
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF not installed. Run: uv add pymupdf"
        ) from exc

    pages: list[tuple[int, bytes]] = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        for i, page in enumerate(doc, start=1):
            pix = page.get_pixmap(dpi=200)
            pages.append((i, pix.tobytes("png")))
    return pages


def run_strategy_c(processor: GeminiDocumentProcessor, source: DocumentSource) -> TradeSetupList:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=processor._api_key)  # noqa: SLF001
    all_setups: list[TradeSetup] = []
    for page_num, png in render_pdf_pages(source.data):
        print(f"  · page {page_num}: {len(png)//1024} KB", flush=True)
        doc_part = types.Part.from_bytes(data=png, mime_type="image/png")
        response = client.models.generate_content(
            model=processor._vision_model,  # noqa: SLF001
            contents=[doc_part, PER_PAGE_PROMPT],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=TradeSetupList,
                temperature=0.0,
            ),
        )
        parsed = getattr(response, "parsed", None)
        if not isinstance(parsed, TradeSetupList):
            parsed = TradeSetupList.model_validate_json(response.text)
        all_setups.extend(parsed.setups)
    return TradeSetupList(setups=all_setups)


# ---------------------------------------------------------------------------
# Pretty printing
# ---------------------------------------------------------------------------
def print_setup(s: TradeSetup) -> None:
    tps = ", ".join(str(t) for t in s.tp) or "—"
    print(
        f"  [{s.ticker:<6}] dir={s.direction:<7} entry={s.entry or '—':<10} "
        f"TP={tps:<25} SL={s.sl or '—':<10} lev={s.leverage or '—':<5} conf={s.confidence:.2f}"
    )
    if s.note:
        print(f"           note: {s.note}")


def print_setups(label: str, setups: list[TradeSetup], asset_filter: str | None) -> None:
    print(f"\n=== {label} ===")
    if asset_filter:
        setups = [s for s in setups if s.ticker.upper() == asset_filter.upper()]
        if not setups:
            print(f"  (no setup found for {asset_filter})")
            return
    for s in setups:
        print_setup(s)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
@dataclass
class Args:
    pdf: Path
    only: str | None
    asset: str | None


def parse_args() -> Args:
    p = argparse.ArgumentParser()
    p.add_argument("pdf", type=Path, help="Path to the PDF to test.")
    p.add_argument("--only", choices=["A", "B", "C"], help="Run a single strategy.")
    p.add_argument("--asset", help="Filter printed output to one ticker (e.g. SOL).")
    ns = p.parse_args()
    return Args(pdf=ns.pdf, only=ns.only, asset=ns.asset)


def main() -> None:
    args = parse_args()
    if not args.pdf.exists():
        sys.exit(f"file not found: {args.pdf}")

    mime, _ = mimetypes.guess_type(args.pdf.name)
    if mime != "application/pdf":
        sys.exit(f"expected PDF, got {mime}")

    data = args.pdf.read_bytes()
    source = DocumentSource(filename=args.pdf.name, mime_type=mime, data=data)
    processor = GeminiDocumentProcessor()

    print(f"PDF: {args.pdf.name} ({len(data)//1024} KB)")
    print(
        f"models | default={settings.gemini_model} | "
        f"vision={settings.vision_model} | extract={settings.extract_model}"
    )

    run = lambda name: not args.only or args.only == name  # noqa: E731

    # ---- A: production pipeline ----
    if run("A"):
        print("\n[A] production two-pass (extract_profile)…")
        t0 = time.perf_counter()
        result = processor.extract_profile(source)
        dt = time.perf_counter() - t0
        print(f"  took {dt:.1f}s, extracted_text length={len(result.extracted_text or '')}")
        print("  --- raw extracted_text (vision dump) ---")
        print(result.extracted_text or "(empty)")
        print("  --- end ---")

    # ---- B: single-shot multimodal ----
    if run("B"):
        print("\n[B] single-shot multimodal + schema…")
        t0 = time.perf_counter()
        try:
            b = run_strategy_b(processor, source)
            dt = time.perf_counter() - t0
            print(f"  took {dt:.1f}s, {len(b.setups)} setups")
            print_setups("Strategy B setups", b.setups, args.asset)
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED: {exc}")

    # ---- C: per-page rendering ----
    if run("C"):
        print("\n[C] per-page render…")
        t0 = time.perf_counter()
        try:
            c = run_strategy_c(processor, source)
            dt = time.perf_counter() - t0
            print(f"  took {dt:.1f}s, {len(c.setups)} setups")
            print_setups("Strategy C setups", c.setups, args.asset)
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED: {exc}")


if __name__ == "__main__":
    main()
