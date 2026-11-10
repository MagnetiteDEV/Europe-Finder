"""jobs.ac.uk adapter (UK academic jobs, HTML listing + JSON-LD detail).

Source: https://www.jobs.ac.uk/search/?keywords=<kw>
- robots.txt allows the search listing (only /job/feedback/ and
  /enhanced/fp/ are disallowed), so a polite read is allowed.
- There is no public API or RSS. The listing is server-rendered
  HTML; each card carries the advert id, title, employer, location
  and an "Expires <day> <Mon>" date. The detail page carries a
  complete JSON-LD block (title, description, datePosted,
  validThrough, hiringOrganization, jobLocation) — the adapter
  reads that instead of scraping description HTML.
- Two-stage fetch: search cards are pre-filtered by title (any
  vocab anchor/phrase, or phd/doctoral/studentship) and only the
  survivors get a detail fetch, capped per run so the source stays
  polite. The engine matcher does the final scoring on the full
  description.
"""
from __future__ import annotations

import json
import re
from datetime import date
from html import unescape
from html.parser import HTMLParser

from requests.exceptions import ConnectionError, Timeout

from ..http import SourceBlocked, polite_get
from ..match import contains_term, normalize_text
from ..vocab import ANCHORS, FIELD_GROUPS
from . import FoundPosting

BASE = "https://www.jobs.ac.uk"
SEARCH_URL = BASE + "/search/"
SOURCE = "jobsacuk"

_ID_RE = re.compile(r"^/job/([A-Z0-9]+)/")
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul",
     "Aug", "Sep", "Oct", "Nov", "Dec"])}
_COUNTRY = {"United Kingdom": "GB", "UK": "GB", "England": "GB",
            "Scotland": "GB", "Wales": "GB", "Ireland": "IE"}

# permissive title pre-filter: any vocab anchor/phrase, or a PhD word
_ANCHOR_WORDS: set[str] = set()
for _terms in ANCHORS.values():
    _ANCHOR_WORDS.update(_terms)
for _fa, _w, _terms in FIELD_GROUPS.values():
    _ANCHOR_WORDS.update(_terms)
_PHDRX = re.compile(r"\b(phd|doctoral|doctorate|studentship)\b", re.I)


def _title_matches(title: str) -> bool:
    if _PHDRX.search(title):
        return True
    t = normalize_text(title)
    return any(contains_term(t, w) for w in _ANCHOR_WORDS)


class _CardParser(HTMLParser):
    """Collects search-result cards from a jobs.ac.uk search page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards: list[dict] = []
        self._cur: dict | None = None
        self._depth = 0
        self._in_title_a = False
        self._in_dept = False
        self._in_emp = False
        self._in_exp = False
        self._buf = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "")
        if tag == "div" and "j-search-result__result" in cls and self._cur is None:
            self._cur = {"id": "", "slug": "", "title": "", "dept": "",
                         "employer": "", "expires": ""}
            self._depth = 1
            return
        if self._cur is None:
            return
        if tag == "div":
            self._depth += 1
        if tag == "a" and a.get("href", "").startswith("/job/"):
            m = _ID_RE.match(a["href"])
            if m:
                self._cur["id"] = m.group(1)
                self._cur["slug"] = a["href"]
                self._in_title_a = True
                self._buf = ""
        elif tag == "div" and "j-search-result__department" in cls:
            self._in_dept = True
            self._buf = ""
        elif tag == "div" and "j-search-result__employer" in cls:
            self._in_emp = True
            self._buf = ""
        elif tag == "span" and "j-search-result__date--blue" in cls:
            self._in_exp = True
            self._buf = ""

    def handle_endtag(self, tag):
        if self._cur is None:
            return
        if tag == "div":
            self._depth -= 1
            if self._depth <= 0:
                if self._cur["id"] and self._cur["title"]:
                    self.cards.append(self._cur)
                self._cur = None
                return
        if tag == "a" and self._in_title_a:
            self._cur["title"] = self._buf.strip()
            self._in_title_a = False
            self._buf = ""
        elif tag == "div" and self._in_dept:
            self._cur["dept"] = self._buf.strip()
            self._in_dept = False
            self._buf = ""
        elif tag == "div" and self._in_emp:
            self._cur["employer"] = self._buf.strip()
            self._in_emp = False
            self._buf = ""
        elif tag == "span" and self._in_exp:
            self._cur["expires"] = self._buf.strip()
            self._in_exp = False
            self._buf = ""

    def handle_data(self, data):
        if self._cur is None:
            return
        if self._in_title_a or self._in_dept or self._in_emp or self._in_exp:
            self._buf += data


def _next_occurrence(day_month: str) -> str:
    """'15 Jan' -> next occurrence as ISO date (search cards lack a year)."""
    m = re.match(r"(\d{1,2})\s+([A-Za-z]{3})", day_month or "")
    if not m or m.group(2) not in _MONTHS:
        return ""
    today = date.today()
    y = today.year
    try:
        d = date(y, _MONTHS[m.group(2)], int(m.group(1)))
    except ValueError:
        return ""
    if d < today:
        d = date(y + 1, _MONTHS[m.group(2)], int(m.group(1)))
    return d.isoformat()


def _parse_detail(html: str) -> dict | None:
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>',
                  html, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(1))
    except Exception:
        return None
    if not isinstance(d, dict) or not d.get("title"):
        return None
    return d


def _from_detail(card: dict, d: dict) -> FoundPosting:
    desc = re.sub(r"<[^>]+>", " ", d.get("description") or "")
    locs = d.get("jobLocation") or []
    city, country = "", ""
    if locs and isinstance(locs, list):
        addr = (locs[0] or {}).get("address") or {}
        city = addr.get("addressLocality", "") or ""
        country = _COUNTRY.get(addr.get("addressCountry", ""), "")
    valid = (d.get("validThrough") or "")[:10]
    posted = (d.get("datePosted") or "")[:10]
    org = ""
    hiring = d.get("hiringOrganization") or {}
    if isinstance(hiring, dict):
        org = hiring.get("name", "") or ""
    return FoundPosting(
        source=SOURCE,
        external_id=card["id"],
        title=" ".join(unescape(d.get("title") or card["title"]).split()),
        organization=" ".join(unescape(org or card["employer"]).split()),
        country=country,
        city=" ".join(unescape(city).split()),
        url=BASE + card["slug"],
        description=" ".join(unescape(desc).split()),
        posted_date=posted,
        deadline=valid or _next_occurrence(card["expires"]),
    )


def search(session, cfg: dict) -> list[FoundPosting]:
    out: list[FoundPosting] = []
    seen: set[str] = set()
    max_details = int(cfg.get("max_details", 30))
    details = 0
    for kw in cfg.get("keywords", []):
        if details >= max_details:
            break
        try:
            r = polite_get(session, SEARCH_URL, params={
                "keywords": kw, "location": "", "distance": "0",
                "category": "0"})
        except SourceBlocked:
            break
        p = _CardParser()
        p.feed(r.text)
        for card in p.cards:
            if card["id"] in seen:
                continue
            seen.add(card["id"])
            if not _title_matches(card["title"] + " " + card["dept"]):
                continue
            if details >= max_details:
                break
            try:
                dr = polite_get(session, BASE + card["slug"])
            except SourceBlocked:
                return out
            except (Timeout, ConnectionError):
                # one slow detail page must not kill the source
                continue
            details += 1
            d = _parse_detail(dr.text)
            if d:
                out.append(_from_detail(card, d))
    return out
