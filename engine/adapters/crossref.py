"""Crossref works adapter (keyless public API).

Discovers researchers by their recent publications in the
candidate's fields:
  GET https://api.crossref.org/works?query=<kw>
      &filter=from-pub-date:<since>,type:journal-article
      &rows=N&select=DOI,title,author,published
Authors are aggregated across works; an author is kept when at
least one matched work carries their name. Affiliation and ORCID
come from the author record when the publisher supplied them
(Crossref coverage is partial — missing values stay empty).
"""
from __future__ import annotations

from ..http import SourceBlocked, polite_get
from ..professors import Professor

WORKS_URL = "https://api.crossref.org/works"
SOURCE = "crossref"


def _year(item: dict) -> str:
    parts = (item.get("published") or {}).get("date-parts") or []
    if parts and parts[0]:
        return str(parts[0][0])
    return ""


def search(session, cfg: dict) -> list[Professor]:
    by_key: dict[str, Professor] = {}
    rows = int(cfg.get("rows", 20))
    since = cfg.get("since", "2023-01-01")
    for kw in cfg.get("keywords", []):
        try:
            r = polite_get(session, WORKS_URL, params={
                "query": kw,
                "filter": f"from-pub-date:{since},type:journal-article",
                "rows": rows,
                "select": "DOI,title,author,published",
            })
        except SourceBlocked:
            break
        for item in r.json().get("message", {}).get("items", []):
            title = (item.get("title") or [""])[0]
            if not title:
                continue
            work = {"title": title, "year": _year(item),
                    "doi": item.get("DOI", "")}
            for a in item.get("author") or []:
                name = " ".join(x for x in [
                    (a.get("given") or "").strip(),
                    (a.get("family") or "").strip()] if x)
                if not name:
                    continue
                orcid = (a.get("ORCID") or "").replace(
                    "https://orcid.org/", "").replace(
                    "http://orcid.org/", "").strip()
                affs = [x.get("name", "") for x in
                        (a.get("affiliation") or []) if x.get("name")]
                key = ("orcid::" + orcid) if orcid else (
                    "name::" + name.lower() + "||" +
                    (affs[0].lower() if affs else ""))
                p = by_key.get(key)
                if p is None:
                    p = Professor(
                        name=name, orcid=orcid,
                        affiliation=affs[0] if affs else "",
                        profile_url=(f"https://orcid.org/{orcid}"
                                     if orcid else ""),
                        sources=[SOURCE])
                    by_key[key] = p
                if work not in p.works:
                    p.works.append(work)
                if not p.affiliation and affs:
                    p.affiliation = affs[0]
    return list(by_key.values())
