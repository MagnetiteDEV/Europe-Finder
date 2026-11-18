"""PageUp classic adapter (Australian universities: UNSW, Monash,
Adelaide, Deakin).

PageUp's classic candidate portal renders server-side HTML:
  <base>/listing/?page=N&page-items=20
Rows: <a class="job-link" href="/<tenant>/cw/en/job/<id>/<slug>">
(title), <span class="location">, <time datetime="ISO"> (closes
date), and a following <tr class="summary"> with a one-line
description. Each job link appears twice per page — dedupe by the
numeric job id. robots.txt on careers.pageuppeople.com disallows
only admin/UAT paths; /cw/ is allowed (Deakin's own host carries
the standard PageUp set, listing allowed).

Volume forces a title pre-filter (UNSW 841 + Monash 513 + Adelaide
1220 + Deakin jobs would otherwise flood the bundle with ~2500
mostly-STEM rows): a listing is kept when its title matches the
engine vocabulary, a PhD word, or bare "design" without a
design-veto term (so "Senior Lecturer – Design" survives while
"UX Designer" / "Industrial Design" do not). The engine matcher
does the final scoring on title + summary; no detail fetch is
done in v2.9. Pages are capped per tenant (config) and the loop
stops early when a page yields no new ids.
"""
from __future__ import annotations

import re
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from ..http import SourceBlocked, polite_get
from ..match import contains_term, normalize_text
from ..vocab import ANCHORS, DESIGN_VETO, FIELD_GROUPS
from . import FoundPosting

SOURCE = "pageup"

_ID_RE = re.compile(r"/job/(\d+)/")
_PHDRX = re.compile(r"\b(phd|doctoral|doctorate|studentship)\b", re.I)

_PREFILTER: set[str] = set()
for _terms in ANCHORS.values():
    _PREFILTER.update(_terms)
for _fa, _w, _terms in FIELD_GROUPS.values():
    _PREFILTER.update(_terms)


def _title_matches(title: str) -> bool:
    if _PHDRX.search(title):
        return True
    t = normalize_text(title)
    if any(contains_term(t, w) for w in _PREFILTER):
        return True
    # bare "design" without a digital/tech-design veto term
    if contains_term(t, "design") and not any(
            contains_term(t, v) for v in DESIGN_VETO):
        return True
    return False


class _ListingParser(HTMLParser):
    """Collects job rows + summary rows from a PageUp listing page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards: list[dict] = []
        self._cur: dict | None = None
        self._in_title_a = False
        self._in_location = False
        self._in_summary = False
        self._buf = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "")
        if tag == "a" and "job-link" in cls:
            m = _ID_RE.search(a.get("href", ""))
            if m:
                self._cur = {"id": m.group(1), "href": a["href"],
                             "title": "", "location": "", "closes": "",
                             "summary": ""}
                self._in_title_a = True
                self._buf = ""
            return
        if tag == "tr" and "summary" in cls:
            self._in_summary = True
            self._buf = ""
            return
        if self._cur is None:
            return
        if tag == "span" and "location" in cls:
            self._in_location = True
            self._buf = ""
        elif tag == "time" and a.get("datetime"):
            self._cur["closes"] = a["datetime"][:10]

    def handle_endtag(self, tag):
        if tag == "a" and self._in_title_a:
            if self._cur is not None:
                self._cur["title"] = self._buf.strip()
                self.cards.append(self._cur)
            self._in_title_a = False
            self._buf = ""
        elif tag == "span" and self._in_location:
            if self._cur is not None:
                self._cur["location"] = self._buf.strip()
            self._in_location = False
            self._buf = ""
        elif tag == "tr" and self._in_summary:
            # summary belongs to the most recent card; set only once
            # (duplicate rows repeat the same summary)
            if self.cards and not self.cards[-1]["summary"]:
                self.cards[-1]["summary"] = self._buf.strip()
            self._in_summary = False
            self._buf = ""

    def handle_data(self, data):
        if self._in_title_a or self._in_location or self._in_summary:
            self._buf += data


def _fetch_tenant(session, tenant: dict, max_pages: int,
                  delay: float) -> list[FoundPosting]:
    base = tenant["base"].rstrip("/")
    origin = f"{urlsplit(base).scheme}://{urlsplit(base).netloc}"
    out: list[FoundPosting] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        try:
            r = polite_get(session, base + "/listing/",
                           params={"page": page, "page-items": 20})
        except SourceBlocked:
            raise
        p = _ListingParser()
        p.feed(r.text)
        new_ids = 0
        for c in p.cards:
            if c["id"] in seen:
                continue
            seen.add(c["id"])
            new_ids += 1
            if not c["title"] or not _title_matches(c["title"]):
                continue
            loc = c["location"]
            out.append(FoundPosting(
                source=SOURCE,
                external_id=f"{tenant.get('code', tenant['name'])}:{c['id']}",
                title=" ".join(c["title"].split()),
                organization=tenant["name"],
                city=loc.split(",")[0].strip() if loc else "",
                url=urljoin(origin, c["href"]),
                description=" ".join(c["summary"].split()),
                deadline=c["closes"],
            ))
        if new_ids == 0:
            break
        time.sleep(delay)
    return out


def search(session, cfg: dict) -> list[FoundPosting]:
    out: list[FoundPosting] = []
    max_pages = int(cfg.get("max_pages", 25))
    delay = float(cfg.get("delay_seconds", 1.5))
    for tenant in cfg.get("tenants", []):
        try:
            out.extend(_fetch_tenant(session, tenant, max_pages, delay))
        except SourceBlocked:
            break
        except Exception as e:  # one tenant must not kill the source
            print(f"  [pageup] {tenant.get('name')}: skipped ({e})")
            continue
    return out
