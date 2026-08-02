#!/usr/bin/env python
"""Freeze the candle cache into an immutable, manifested snapshot.

The audit's first continuation condition: the two arms of a controlled
comparison saw different venue data because the live cache refreshed between
them. The fix is not discipline, it is immutability — copy the cache once,
hash every file, and point FINCOACH_FROZEN_DATA at the copy. Every later run
against the snapshot is then bit-for-bit reproducible or loudly broken.

Honest limit, recorded in the manifest: the snapshot freezes the cache AS IT
IS. Historical cross-venue seams already inside a cached series (merged before
freezing existed) are frozen along with it; the manifest records each file's
single source label, which cannot prove seamlessness.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.quant.exchange import CACHE_DIR  # noqa: E402

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def main() -> None:
    stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    dest = os.path.join(BASE, "frozen", stamp)
    os.makedirs(dest, exist_ok=True)

    manifest: dict[str, dict] = {}
    for name in sorted(os.listdir(CACHE_DIR)):
        if not name.endswith(".json"):
            continue
        src = os.path.join(CACHE_DIR, name)
        with open(src, "rb") as fh:
            raw = fh.read()
        blob = json.loads(raw)
        rows = blob.get("rows", [])
        manifest[name] = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "source": blob.get("source"),
            "n_bars": len(rows),
            "first_ts": int(rows[0][0]) if rows else None,
            "last_ts": int(rows[-1][0]) if rows else None,
        }
        shutil.copy2(src, os.path.join(dest, name))

    with open(os.path.join(dest, "MANIFEST.json"), "w", encoding="utf-8") as fh:
        json.dump(
            {
                "frozen_at": int(time.time()),
                "frozen_from": CACHE_DIR,
                "note": (
                    "Snapshot of the live cache. Single source label per file; "
                    "pre-freeze cross-venue seams, if any, are frozen as-is."
                ),
                "files": manifest,
            },
            fh, indent=1,
        )
    print(dest)
    print(f"{len(manifest)} series frozen")


if __name__ == "__main__":
    main()
