import json, traceback, sys
from app.tools import market_tools

try:
    res = market_tools.analyze_ticker_8dim.invoke({"ticker": "AAPL", "fast": True})
    print(json.dumps(res, indent=2, ensure_ascii=False))
except Exception:
    traceback.print_exc()
    sys.exit(1)
