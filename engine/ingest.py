"""Ingestion run: adapters -> normalize -> policy engine -> dedupe
-> SQLite + JSON.

The policy engine applies the candidate's search constraints:
multilingual subject match with engineering exclusions, strict
funding classification, recorded (never inferred) Iranian
eligibility, and priority-country flagging.

Usage:  .venv/bin/python -m engine.ingest   (from project root)
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from .adapters import FoundPosting
from .adapters import adzuna, ats, rss_nature
from .curated import load_all as load_curated
from .eligibility import load_overrides, status_for
from .extract import detect_kind, extract_country, extract_deadline
from .funding import FA_LABEL as FUNDING_FA
from .funding import classify_funding
from .http import SourceBlocked, make_session
from .match import score_posting
from .vocab import FIELD_GROUPS

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

ADAPTERS = {
    "nature": rss_nature.search,
    "adzuna": adzuna.search,
    "ats": ats.search,
}


def normalize(p: FoundPosting) -> FoundPosting:
    p.title = " ".join((p.title or "").split())
    p.description = " ".join((p.description or "").split())
    if not p.country:
        p.country = extract_country(p.city + " " + p.description, "")
    if not p.deadline:
        p.deadline = extract_deadline(p.description)
    return p


def apply_policy(p: FoundPosting, policy: dict, elig_overrides: dict) -> None:
    """Subject match, funding, eligibility, priority country, kind."""
    score_posting(p)
    cat, notes, flags = classify_funding(p.title, p.description)
    p.funding_category = cat
    p.funding_fa = FUNDING_FA[cat]
    p.funding_notes = notes
    p.red_flags = (p.red_flags or []) + flags
    status, note = status_for(p.key(), elig_overrides)
    p.eligibility = status
    p.eligibility_note = note
    p.priority_country = p.country in policy.get("priorityCountries", [])
    if not getattr(p, "curated", False):
        p.kind = detect_kind(p.title, p.description)


def save_sqlite(posts: list[FoundPosting]) -> None:
    DATA.mkdir(exist_ok=True)
    con = sqlite3.connect(DATA / "postings.db")
    con.execute("""CREATE TABLE IF NOT EXISTS postings
                   (key TEXT PRIMARY KEY, payload TEXT)""")
    for p in posts:
        con.execute("INSERT OR REPLACE INTO postings VALUES (?, ?)",
                    (p.key(), json.dumps(p.to_dict(), ensure_ascii=False)))
    con.commit()
    con.close()


def main() -> None:
    t0 = time.time()
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    policy = json.loads((ROOT / "policy.json").read_text(encoding="utf-8"))
    elig_overrides = load_overrides(ROOT)
    session = make_session()

    collected: list[FoundPosting] = []
    for name, fn in ADAPTERS.items():
        scfg = cfg.get("sources", {}).get(name, {})
        if not scfg.get("enabled"):
            print(f"[{name}] disabled, skipping")
            continue
        try:
            posts = fn(session, scfg)
        except SourceBlocked as e:
            print(f"[{name}] blocked ({e}), skipping rest of source")
            continue
        except Exception as e:  # one source must not kill the run
            print(f"[{name}] error: {e}")
            continue
        print(f"[{name}] {len(posts)} raw postings")
        collected.extend(posts)
        time.sleep(float(cfg.get("politeness", {}).get("delay_seconds", 1.5)))

    # curated funding routes: verified official entries, no HTTP needed
    try:
        curated = load_curated()
        print(f"[curated] {len(curated)} funding routes")
        collected.extend(curated)
    except Exception as e:
        print(f"[curated] error: {e}")

    # normalize + policy + dedupe (keep highest score per key)
    best: dict[str, FoundPosting] = {}
    for p in collected:
        normalize(p)
        apply_policy(p, policy, elig_overrides)
        if getattr(p, "curated", False) and getattr(p, "_funding_preset", None):
            # curated entries carry their verified funding classification
            cat, fa, notes = p._funding_preset
            p.funding_category, p.funding_fa, p.funding_notes = cat, fa, notes
        k = p.key()
        if k not in best or p.fit_score > best[k].fit_score:
            best[k] = p
    # excluded postings sink to the bottom of the default view
    posts = sorted(best.values(),
                   key=lambda p: (p.excluded, -p.fit_score,
                                  p.deadline or "9999"))

    # Degraded-run guard: if ATS was enabled but this run fetched nothing
    # (e.g. the run context has no egress to university endpoints) while the
    # previous postings.json still holds ATS postings, keep those instead of
    # wiping the app's data. Stale data beats an empty app; the warning stays
    # loud so a monitoring cron can report it.
    ats_enabled = cfg.get("sources", {}).get("ats", {}).get("enabled")
    if ats_enabled and not any(p.source.startswith("ats:") for p in posts):
        prev_file = DATA / "postings.json"
        prev_ats: list[dict] = []
        if prev_file.exists():
            try:
                prev_ats = [p for p in json.loads(
                    prev_file.read_text(encoding="utf-8")).get("postings", [])
                    if p.get("source", "").startswith("ats:")]
            except Exception:
                prev_ats = []
        if prev_ats:
            from dataclasses import fields as dc_fields
            fnames = {f.name for f in dc_fields(FoundPosting)}
            have = {p.key() for p in posts}
            merged = 0
            for d in prev_ats:
                fp = FoundPosting(
                    **{k: v for k, v in d.items() if k in fnames})
                if fp.key() not in have:
                    posts.append(fp)
                    have.add(fp.key())
                    merged += 1
            posts.sort(key=lambda p: (p.excluded, -p.fit_score,
                                      p.deadline or "9999"))
            print(f"[ats] WARNING: fetch returned 0 postings; kept "
                  f"{merged} previous ATS postings (data may be stale)")

    save_sqlite(posts)
    payload = {
        "meta": {
            "version": 2,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sources": sorted({p.source for p in posts}),
            "count": len(posts),
            "groups": [fa for fa, _, _ in FIELD_GROUPS.values()],
            "priority_countries": policy.get("priorityCountries", []),
        },
        "postings": [p.to_dict() for p in posts],
    }
    (DATA / "postings.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    bands: dict[str, int] = {}
    funding: dict[str, int] = {}
    for p in posts:
        bands[p.fit_band] = bands.get(p.fit_band, 0) + 1
        funding[p.funding_category] = funding.get(p.funding_category, 0) + 1
    print(f"done: {len(posts)} postings in {time.time()-t0:.1f}s")
    print(f"  bands: {bands}")
    print(f"  funding: {funding}")


if __name__ == "__main__":
    main()
