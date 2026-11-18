"""Campus France Master's catalogue adapter (France).

Undocumented JSON web service behind the Campus France catalogue:
  list:   https://cataloguelm.campusfrance.org/master/ws/getmasterwkwjson.php?listkeys=<kw>
  detail: https://cataloguelm.campusfrance.org/master/ws/getmasterformjson.php?id=<id>
The list returns {"programs": [{id, fla, fle, cl, ela, ...}]}; the
detail returns {etab: {le, lv, url}, form: {lf, tf, fu, parcours},
filiere: [{laben}]}. The programme URL is form.fu (the human
deep-link #/program/<id> was not verified, so it is not used).

Keyword choice matters: bare "mode" returns 206 hits including
engineering "modélisation", so only English keywords are used
(config) and the engine matcher does the final scoring. The
catalogue has no dates/deadlines and updates twice a year
(April + October); daily polling is harmless (a handful of small
JSON requests) and keeps the adapter uniform with the rest.
No robots file exists on the catalogue host.
"""
from __future__ import annotations

import time

from requests.exceptions import ConnectionError, Timeout

from ..http import SourceBlocked, polite_get
from . import FoundPosting

LIST_URL = ("https://cataloguelm.campusfrance.org/master/ws/"
            "getmasterwkwjson.php")
DETAIL_URL = ("https://cataloguelm.campusfrance.org/master/ws/"
              "getmasterformjson.php")
SOURCE = "campusfrance"


def _from_detail(prog: dict, d: dict) -> FoundPosting:
    etab = d.get("etab") or {}
    form = d.get("form") or {}
    filiere = d.get("filiere") or []
    title = (form.get("lf") or prog.get("fla") or "").strip()
    org = (etab.get("le") or prog.get("ela") or "").strip()
    city = (etab.get("lv") or prog.get("cl") or "").strip()
    url = (form.get("fu") or etab.get("url") or "").strip()
    parts = [title, org]
    level = form.get("tf") or prog.get("fle") or ""
    if level:
        parts.append(f"Level: {level}")
    labels = [f.get("laben") or f.get("l") for f in filiere if f.get("laben") or f.get("l")]
    if labels:
        parts.append("Field: " + ", ".join(labels))
    parcours = form.get("parcours") or []
    if parcours:
        parts.append("Tracks: " + "; ".join(parcours))
    post = FoundPosting(
        source=SOURCE,
        external_id=str(prog.get("id", "")),
        title=" ".join(title.split()),
        organization=" ".join(org.split()),
        country="FR",
        city=" ".join(city.split()),
        url=url,
        description=" ".join(" ".join(parts).split()),
    )
    post.kind = "master"
    post._kind_fixed = True
    return post


def _from_list(prog: dict) -> FoundPosting:
    post = FoundPosting(
        source=SOURCE,
        external_id=str(prog.get("id", "")),
        title=" ".join((prog.get("fla") or "").split()),
        organization=" ".join((prog.get("ela") or "").split()),
        country="FR",
        city=" ".join((prog.get("cl") or "").split()),
        description=" ".join((prog.get("fla") or "").split()),
    )
    post.kind = "master"
    post._kind_fixed = True
    return post


def search(session, cfg: dict) -> list[FoundPosting]:
    out: list[FoundPosting] = []
    delay = float(cfg.get("delay_seconds", 1.5))
    cap = int(cfg.get("max_details", 60))
    programs: dict[str, dict] = {}
    for kw in cfg.get("keywords", []):
        try:
            r = polite_get(session, LIST_URL, params={"listkeys": kw})
        except SourceBlocked:
            break
        try:
            payload = r.json()
        except Exception:
            continue
        for prog in payload.get("programs", []) or []:
            pid = str(prog.get("id", ""))
            if pid and pid not in programs:
                programs[pid] = prog
        time.sleep(delay)
    details = 0
    for pid, prog in programs.items():
        if details >= cap:
            out.append(_from_list(prog))
            continue
        try:
            time.sleep(delay)
            r = polite_get(session, DETAIL_URL, params={"id": pid})
            details += 1
            out.append(_from_detail(prog, r.json()))
        except SourceBlocked:
            out.append(_from_list(prog))
            break
        except (Timeout, ConnectionError, ValueError):
            out.append(_from_list(prog))
    return out
