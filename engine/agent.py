"""Daily agent (Dossier-style): diff against seen postings, keep the
best new ones with their reasons, write the digest the PWA shows as
«پیشنهادهای امروز».

Usage:  .venv/bin/python -m engine.agent   (after ingest)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MIN_SCORE = 70
MAX_PICKS = 30


def main() -> None:
    postings_path = DATA / "postings.json"
    if not postings_path.exists():
        print("no postings.json — run ingest first")
        return
    payload = json.loads(postings_path.read_text(encoding="utf-8"))
    postings = payload["postings"]

    seen_path = DATA / "seen.json"
    seen: set[str] = set(json.loads(seen_path.read_text(encoding="utf-8"))
                         if seen_path.exists() else [])

    new = [p for p in postings
           if f"{p['source']}::{p['external_id']}" not in seen]

    # The digest is the agent's current top picks among *live* postings
    # (score >= MIN_SCORE, best first) — robust across quiet days and
    # backfills naturally after any re-ingest.
    live_picks = sorted(
        (p for p in postings if p["fit_score"] >= MIN_SCORE),
        key=lambda p: -p["fit_score"])[:MAX_PICKS]

    digest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "new_count": len(new),
        "picks": live_picks,
    }
    (DATA / "digest.json").write_text(
        json.dumps(digest, ensure_ascii=False, indent=1), encoding="utf-8")
    seen |= {f"{p['source']}::{p['external_id']}" for p in postings}
    seen_path.write_text(json.dumps(sorted(seen), ensure_ascii=False),
                         encoding="utf-8")
    print(f"agent: {len(new)} new, {len(live_picks)} live picks "
          f"(score>={MIN_SCORE})")


if __name__ == "__main__":
    main()
