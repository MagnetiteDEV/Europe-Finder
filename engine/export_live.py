"""Publish the live data bundle for the single-file app.

Writes <output> as:  window.__EOF_LIVE__ = {...};
The global name MUST stay __EOF_LIVE__ (not EOF_DATA) so the app can
validate the payload before swapping it in (see liveData() in app.js).

Only non-personal data is exported: the candidate profile itself
(profile.json) NEVER leaves the project directory.

Usage:  .venv/bin/python -m engine.export_live /path/to/eof-live.js
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .export_web import build_bundle


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m engine.export_live <output-js-path>", file=sys.stderr)
        sys.exit(2)
    out = Path(sys.argv[1])
    bundle = build_bundle()
    js = ("window.__EOF_LIVE__ = " +
          json.dumps(bundle, ensure_ascii=False) + ";\n")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(js, encoding="utf-8")
    print(f"exported {len(bundle['postings'])} postings -> {out}")


if __name__ == "__main__":
    main()
