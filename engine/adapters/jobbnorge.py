"""Jobbnorge adapter (Norway — salaried PhD Research Fellowships).

Covers Norwegian universities and art academies (KHiO Oslo, KMD Bergen,
AHO, NTNU, UiO, UiB). All Norwegian PhD Research Fellow (Stipendiat)
positions are 3-4 year salaried public-sector employment contracts.

v2.9.4: the old /en/available-jobs HTML listing is gone (404 — the site
moved to a JS app at jobbnorge.no/search). This adapter now uses the
site's own public JSON API (https://publicapi.jobbnorge.no/v3/jobs,
found in the site's search bundle): one call returns the full job list
(the `search` query param is ignored server-side — filtering happens
client-side, same as the site itself), so this adapter filters in Python:
title must carry a PhD marker (PhD / Stipendiat / doktorgrad) and the
title+summary must carry an arts signal (config keywords or Norwegian
arts terms); the engine matcher applies the final arts lens.
"""
from __future__ import annotations

import re
import time
from datetime import datetime

from requests.exceptions import ConnectionError, Timeout

from ..http import SourceBlocked, polite_get
from . import FoundPosting

API_URL = "https://publicapi.jobbnorge.no/v3/jobs"
SOURCE = "jobbnorge"

_PHD_RE = re.compile(r"\b(ph\.?\s*d\.?|doctoral|stipendiat|doktorgrad)\b", re.I)

# Arts signal: English tokens from the config keywords + Norwegian arts terms.
_ARTS_EN = ("art", "design", "fashion", "museum", "heritage", "visual",
            "costume", "artistic", "textile", "curatorial", "culture")
_ARTS_NO = ("kunst", "mote", "design", "museum", "kulturarv", "visuell",
            "tekstil", "kostyme", "arkitektur", "dans", "teater", "musikk",
            "film", "foto", "grafisk", "illustrasjon", "keramikk",
            "scenografi", "kunstnerisk", "kultur", "historie", "arkeologi",
            "litteratur", "filosofi")
_ARTS_RE = re.compile(
    r"\b(" + "|".join(_ARTS_EN + _ARTS_NO) + r")\b", re.I)

DEFAULT_KEYWORDS = [
    "PhD art", "PhD design", "PhD fashion", "PhD museum",
    "PhD heritage", "PhD visual", "PhD costume", "artistic research",
]


def _parse_deadline(raw: str) -> str:
    """Jobbnorge deadlines are 'DD.MM.YYYY' or 'Løpende' (rolling)."""
    raw = (raw or "").strip()
    if not raw or raw.lower().startswith("l"):
        return ""
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def _parse_api(payload: dict) -> list[FoundPosting]:
    """Filter the public API's full job list down to artistic PhD roles."""
    out: list[FoundPosting] = []
    seen: set[str] = set()
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        return out
    for j in jobs:
        if not isinstance(j, dict):
            continue
        jid = str(j.get("id") or "").strip()
        title = (j.get("title") or "").strip()
        if not jid or not title or jid in seen:
            continue
        summary = (j.get("summary") or "").strip()
        if not _PHD_RE.search(title):
            continue
        if not _ARTS_RE.search(title + " " + summary):
            continue
        seen.add(jid)
        locs = j.get("locations") or []
        primary = next((x for x in locs if isinstance(x, dict) and x.get("isPrimary")),
                       locs[0] if locs else {})
        city = (primary.get("municipality") or primary.get("area") or "").strip()
        dept = (j.get("department") or "").strip()
        desc = summary
        if dept:
            desc = f"{desc} ({dept})".strip()
        posted = str(j.get("publicationDate") or "")
        if re.match(r"^\d{2}\.\d{2}\.\d{4}", posted):
            posted = _parse_deadline(posted[:10])
        else:
            posted = posted[:10]
        p = FoundPosting(
            source=SOURCE,
            external_id=jid,
            title=title,
            organization=(j.get("employer") or "Norwegian Institution (Jobbnorge)").strip(),
            country="NO",
            city=city,
            url=str(j.get("link") or f"https://www.jobbnorge.no/ledige-stillinger/stilling/{jid}"),
            description=desc,
            posted_date=posted,
            deadline=_parse_deadline(str(j.get("deadline") or "")),
        )
        p.kind = "phd"
        p._kind_fixed = True
        out.append(p)
    return out


def search(session, cfg: dict) -> list[FoundPosting]:
    """One API call for the full list; filtering happens here, not per keyword."""
    try:
        r = polite_get(session, API_URL, params={"language": 1}, timeout=30)
    except SourceBlocked:
        return []
    except (Timeout, ConnectionError):
        return []
    except Exception:
        return []
    try:
        payload = r.json()
    except Exception:
        return []
    out = _parse_api(payload)
    time.sleep(float(cfg.get("delay_seconds", 1.5)))
    return out
