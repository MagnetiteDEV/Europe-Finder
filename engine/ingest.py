"""Ingestion run: adapters -> normalize -> policy engine -> cross-source dedupe
-> universal degraded-run guard -> SQLite + JSON.

Upgraded in v2.9.3:
- Adds European salaried/funded PhD adapters: AcademicTransfer (NL),
  Jobbnorge (NO), Campus France Doctorat (FR), myScience.ch (CH),
  University of Copenhagen PhD (DK), plus curated:phd routes.
- Universal per-source degraded-run guard (covers ALL enabled sources,
  not just ATS, preventing single-source outages like 23 Nov from wiping
  DAAD, PhD Germany, jobs.ac.uk or professors).
- Cross-source deduplication with `also_in` provenance.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import fields as dc_fields
from datetime import date, datetime, timezone
from pathlib import Path

from .adapters import FoundPosting
from .adapters import (
    academictransfer,
    adzuna,
    ats,
    campusfrance,
    campusfrance_phd,
    crossref,
    daad,
    euraxess,
    fashionunited,
    feeds,
    jobbnorge,
    jobs_ac_uk,
    nordic_arts,
    orcid,
    pageup,
    rss_nature,
)
from .curated import load_all as load_curated
from .eligibility import load_overrides, status_for
from .extract import clean_plain_text, detect_kind, extract_country, extract_deadline
from .funding import FA_LABEL as FUNDING_FA
from .funding import classify_funding
from .http import SourceBlocked, make_session
from .match import score_posting
from .professors import merge_professors
from .vocab import FIELD_GROUPS

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

ADAPTERS = {
    "nature": rss_nature.search,
    "adzuna": adzuna.search,
    "ats": ats.search,
    "euraxess": euraxess.search,
    "jobsacuk": jobs_ac_uk.search,
    "cumulus": feeds.search_cumulus,
    "arthist": feeds.search_arthist,
    "daad": daad.search,
    "phdgermany": daad.search_phd,
    "campusfrance": campusfrance.search,
    "fashionunited": fashionunited.search,
    "pageup": pageup.search,
    # v2.9.3: expanded European salaried/funded PhD adapters
    "academictransfer": academictransfer.search,
    "jobbnorge": jobbnorge.search,
    "campusfrance_phd": campusfrance_phd.search,
    "myscience": nordic_arts.search_myscience,
    "ku_phd": nordic_arts.search_ku_phd,
}


def normalize(p: FoundPosting) -> FoundPosting:
    p.title = clean_plain_text(p.title or "")
    p.description = clean_plain_text(p.description or "")
    p.organization = clean_plain_text(p.organization or "")
    if not p.country:
        p.country = extract_country(p.city + " " + p.organization + " " + p.description, "")
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
    if not getattr(p, "curated", False) and not getattr(p, "_kind_fixed", False):
        p.kind = detect_kind(p.title, p.description)


def _norm_key_part(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _org_base(org: str) -> str:
    o = (org or "").lower().strip().split(",")[0].strip()
    o = re.sub(r"^the\s+", "", o)
    return _norm_key_part(o)


def cross_source_dedupe(posts: list[FoundPosting]) -> list[FoundPosting]:
    """Merge identical postings fetched from two different sources (e.g.
    jobs.ac.uk + university ATS) and record the secondary source in also_in."""
    out: list[FoundPosting] = []
    seen: dict[tuple[str, str, str], FoundPosting] = {}
    for p in posts:
        if getattr(p, "curated", False):
            out.append(p)
            continue
        nt = _norm_key_part(p.title)
        no = _org_base(p.organization)
        dk = (nt, no, p.kind) if (nt and no) else None
        if dk and dk in seen:
            ex = seen[dk]
            if ex.source != p.source:
                also = list(ex.also_in or [])
                if p.source not in also:
                    also.append(p.source)
                ex.also_in = also
                if not ex.deadline and p.deadline:
                    ex.deadline = p.deadline
                if len(p.description or "") > len(ex.description or ""):
                    ex.description = p.description
                continue
        if dk and dk not in seen:
            seen[dk] = p
        out.append(p)
    return out


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


def _load_previous_bundle() -> tuple[dict, str]:
    """Load previous postings/professors from data/postings.json or docs/eof-live.js."""
    prev_file = DATA / "postings.json"
    if prev_file.exists():
        try:
            payload = json.loads(prev_file.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and payload.get("postings"):
                profs_file = DATA / "professors.json"
                if profs_file.exists():
                    try:
                        payload["professors"] = json.loads(
                            profs_file.read_text(encoding="utf-8")
                        ).get("professors", [])
                    except Exception:
                        pass
                return payload, "data/postings.json"
        except Exception:
            pass
    bundle = ROOT / "docs" / "eof-live.js"
    if bundle.exists():
        try:
            raw = bundle.read_text(encoding="utf-8")
            prefix = "window.__EOF_LIVE__ = "
            if raw.startswith(prefix):
                payload = json.loads(raw[len(prefix):].rstrip().rstrip(";"))
                if isinstance(payload, dict) and payload.get("postings"):
                    return payload, "docs/eof-live.js"
        except Exception:
            pass
    return {}, ""


def _is_not_expired(d: dict) -> bool:
    dl = (d.get("deadline") or "").strip()
    if not dl:
        return True
    try:
        return dl >= date.today().isoformat()
    except Exception:
        return True


def _source_matches_adapter(src: str, adapter_name: str) -> bool:
    if adapter_name == "ats":
        return src.startswith("ats:")
    return src == adapter_name


PROFESSOR_ADAPTERS = {
    "orcid": orcid.search,
    "crossref": crossref.search,
}


def collect_professors(session, cfg: dict, prev_profs: list[dict] | None = None) -> list:
    """Professor discovery (ORCID + Crossref) with degraded-run guard."""
    pcfg = cfg.get("professors", {})
    collected = []
    for name, fn in PROFESSOR_ADAPTERS.items():
        scfg = pcfg.get(name, {})
        if not scfg.get("enabled"):
            print(f"[prof:{name}] disabled, skipping")
            continue
        try:
            profs = fn(session, scfg)
        except SourceBlocked as e:
            print(f"[prof:{name}] blocked ({e}), skipping")
            continue
        except Exception as e:
            print(f"[prof:{name}] error: {e}")
            continue
        print(f"[prof:{name}] {len(profs)} raw professors")
        collected.extend(profs)
        time.sleep(float(cfg.get("politeness", {}).get("delay_seconds", 1.5)))
    merged = merge_professors(collected)
    kept_dicts = [p.to_dict() for p in merged if p.fit_score >= 45][:60]

    # Professor degraded-run guard: never drop >50% of professors on an API rate-limit day
    if prev_profs and len(prev_profs) >= 10 and len(kept_dicts) < len(prev_profs) // 2:
        seen_names = {(x.get("name") or "").lower() for x in kept_dicts}
        restored = 0
        for old in prev_profs:
            nm = (old.get("name") or "").lower()
            if nm and nm not in seen_names:
                kept_dicts.append(old)
                seen_names.add(nm)
                restored += 1
        print(f"[prof] WARNING: degraded fetch ({len(kept_dicts)-restored} vs "
              f"prev {len(prev_profs)}); preserved {restored} previous professors")

    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "count": len(kept_dicts),
            "sources": sorted({s for p in kept_dicts for s in (p.get("sources") or [])}),
        },
        "professors": kept_dicts,
    }
    (DATA / "professors.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[prof] {len(kept_dicts)} professors kept (from {len(merged)} merged)")
    return kept_dicts


def main() -> None:
    t0 = time.time()
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    policy = json.loads((ROOT / "policy.json").read_text(encoding="utf-8"))
    elig_overrides = load_overrides(ROOT)
    session = make_session()

    prev_bundle, prev_origin = _load_previous_bundle()
    prev_postings: list[dict] = prev_bundle.get("postings", []) if isinstance(prev_bundle, dict) else []
    prev_profs: list[dict] = prev_bundle.get("professors", []) if isinstance(prev_bundle, dict) else []

    collected: list[FoundPosting] = []
    enabled_adapters: list[str] = []
    fetched_counts: dict[str, int] = {}

    for name, fn in ADAPTERS.items():
        scfg = cfg.get("sources", {}).get(name, {})
        if not scfg.get("enabled"):
            print(f"[{name}] disabled, skipping")
            continue
        enabled_adapters.append(name)
        try:
            posts = fn(session, scfg)
        except SourceBlocked as e:
            print(f"[{name}] blocked ({e}), skipping rest of source")
            fetched_counts[name] = 0
            continue
        except Exception as e:
            print(f"[{name}] error: {e}")
            fetched_counts[name] = 0
            continue
        fetched_counts[name] = len(posts)
        print(f"[{name}] {len(posts)} raw postings")
        collected.extend(posts)
        time.sleep(float(cfg.get("politeness", {}).get("delay_seconds", 1.5)))

    # curated funding routes (PhDs + Masters + Scholarships): verified official entries
    try:
        curated = load_curated()
        print(f"[curated] {len(curated)} funding routes")
        collected.extend(curated)
    except Exception as e:
        print(f"[curated] error: {e}")

    # normalize + policy + key dedupe
    best: dict[str, FoundPosting] = {}
    for p in collected:
        normalize(p)
        apply_policy(p, policy, elig_overrides)
        if getattr(p, "curated", False) and getattr(p, "_funding_preset", None):
            cat, fa, notes = p._funding_preset
            p.funding_category, p.funding_fa, p.funding_notes = cat, fa, notes
        k = p.key()
        if k not in best or p.fit_score > best[k].fit_score:
            best[k] = p

    posts = sorted(best.values(),
                   key=lambda p: (p.excluded, -p.fit_score, p.deadline or "9999"))
    posts = cross_source_dedupe(posts)

    # Universal per-source degraded-run guard: for ANY enabled adapter that
    # returned 0 postings this run, retain non-expired postings from the
    # previous healthy bundle instead of wiping that source to 0.
    health_warnings: list[str] = []
    if prev_postings:
        fnames = {f.name for f in dc_fields(FoundPosting)}
        have = {p.key() for p in posts}
        for name in enabled_adapters:
            if fetched_counts.get(name, 0) > 0:
                continue
            prev_for_src = [
                d for d in prev_postings
                if isinstance(d, dict)
                and _source_matches_adapter(d.get("source", ""), name)
                and _is_not_expired(d)
            ]
            if not prev_for_src:
                continue
            merged = 0
            for d in prev_for_src:
                fp = FoundPosting(**{k: v for k, v in d.items() if k in fnames})
                if fp.key() not in have:
                    posts.append(fp)
                    have.add(fp.key())
                    merged += 1
            if merged:
                msg = f"منبع {name} امروز ۰ مورد برگرداند — {merged} آگهی منقضی‌نشده از اجرای قبلی حفظ شد"
                health_warnings.append(msg)
                print(f"[{name}] WARNING: fetch returned 0 postings; kept "
                      f"{merged} previous postings from {prev_origin}")

    posts.sort(key=lambda p: (p.excluded, -p.fit_score, p.deadline or "9999"))

    save_sqlite(posts)
    payload = {
        "meta": {
            "version": 2,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sources": sorted({p.source for p in posts}),
            "count": len(posts),
            "groups": [fa for fa, _, _ in FIELD_GROUPS.values()],
            "priority_countries": policy.get("priorityCountries", []),
            "health": {"warnings": health_warnings},
        },
        "postings": [p.to_dict() for p in posts],
    }
    (DATA / "postings.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    bands: dict[str, int] = {}
    funding: dict[str, int] = {}
    kinds: dict[str, int] = {}
    for p in posts:
        bands[p.fit_band] = bands.get(p.fit_band, 0) + 1
        funding[p.funding_category] = funding.get(p.funding_category, 0) + 1
        kinds[p.kind] = kinds.get(p.kind, 0) + 1
    print(f"done: {len(posts)} postings in {time.time()-t0:.1f}s")
    print(f"  kinds: {kinds}")
    print(f"  bands: {bands}")
    print(f"  funding: {funding}")

    try:
        collect_professors(session, cfg, prev_profs=prev_profs)
    except Exception as e:
        print(f"[prof] error: {e}")


if __name__ == "__main__":
    main()
