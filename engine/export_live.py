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


def _previous_count(out: Path) -> int | None:
    """Posting count of the bundle already at <out>, or None when the
    file is missing/unreadable (first publish, or a fresh checkout)."""
    if not out.exists():
        return None
    try:
        raw = out.read_text(encoding="utf-8")
        prefix = "window.__EOF_LIVE__ = "
        if not raw.startswith(prefix):
            return None
        bundle = json.loads(raw[len(prefix):].rstrip().rstrip(";"))
        return len(bundle.get("postings", []))
    except Exception:
        return None


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m engine.export_live <output-js-path>", file=sys.stderr)
        sys.exit(2)
    out = Path(sys.argv[1])
    bundle = build_bundle()
    new_count = len(bundle["postings"])
    # Hollow-bundle guard (2026-11-16): on 2026-11-16 the daily workflow
    # published a 45-posting bundle because ATS + jobs.ac.uk returned
    # nothing on the runner, wiping the app's data. Refuse to overwrite
    # a healthy bundle with one that lost more than half its postings;
    # the workflow then fails without committing, and the previous good
    # bundle stays live. Fail open when there is no previous bundle.
    prev = _previous_count(out)
    if prev is not None and prev > 0 and new_count < prev // 2:
        print(f"REFUSED: new bundle has {new_count} postings, previous "
              f"had {prev} (>50% drop — a source probably failed); "
              f"keeping the previous bundle at {out}", file=sys.stderr)
        sys.exit(1)
    js = ("window.__EOF_LIVE__ = " +
          json.dumps(bundle, ensure_ascii=False) + ";\n")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(js, encoding="utf-8")
    print(f"exported {new_count} postings -> {out}")


if __name__ == "__main__":
    main()
