"""jobs.ac.uk adapter (UK academic jobs & PhD studentships).

Upgraded in v2.9.3:
- Adds polite `delay_seconds` between every search page AND every detail
  fetch (prevents 429/403 rate-limiting that dropped jobsacuk to 0).
- Runs dedicated PhD/Studentship artistic queries FIRST (with its own
  detail quota), before general academic jobs, and pre-rejects obvious
  engineering/STEM titles before spending detail fetches.
- Parses JSON-LD robustly (including extra script tag attributes and
  @graph arrays) and strips HTML cleanly.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date
from html import unescape
from html.parser import HTMLParser

from requests.exceptions import ConnectionError, Timeout

from ..http import SourceBlocked, polite_get
from ..match import contains_term, normalize_text
from ..vocab import ANCHORS, DESIGN_VETO, FIELD_GROUPS, HARD_EXCLUSIONS
from . import FoundPosting
from .ats import strip_html

BASE = "https://www.jobs.ac.uk"
SEARCH_URL = BASE + "/search/"
SOURCE = "jobsacuk"

_ID_RE = re.compile(r"^/job/([A-Z0-9]+)/")
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul",
     "Aug", "Sep", "Oct", "Nov", "Dec"])}
_COUNTRY = {"United Kingdom": "GB", "UK": "GB", "England": "GB",
            "Scotland": "GB", "Wales": "GB", "Ireland": "IE"}

_ANCHOR_WORDS: set[str] = set()
for _terms in ANCHORS.values():
    _ANCHOR_WORDS.update(_terms)
for _fa, _w, _terms in FIELD_GROUPS.values():
    _ANCHOR_WORDS.update(_terms)
_PHDRX = re.compile(r"\b(phd|doctoral|doctorate|studentship|mphil/phd)\b", re.I)

DEFAULT_PHD_KEYWORDS = [
    "phd fashion",
    "phd art history",
    "phd visual culture",
    "phd design",
    "phd museum",
    "phd cultural heritage",
    "phd costume",
    "phd material culture",
    "phd fine art",
    "phd curatorial",
    "phd textile",
]


def _title_matches(title: str, phd_mode: bool = False) -> bool:
    t = normalize_text(title)
    # Pre-reject obvious STEM/engineering & digital-UX titles before spending a detail fetch
    if any(contains_term(t, ex) for ex in HARD_EXCLUSIONS):
        return False
    if any(contains_term(t, dv) for dv in DESIGN_VETO):
        return False
    if any(contains_term(t, w) for w in _ANCHOR_WORDS):
        return True
    if phd_mode and _PHDRX.search(title):
        return True
    return False


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


_LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I)


def _parse_detail(html_text: str) -> dict | None:
    for m in _LD_RE.finditer(html_text):
        try:
            d = json.loads(m.group(1))
        except Exception:
            continue
        if isinstance(d, dict) and d.get("@graph"):
            for item in d["@graph"]:
                if isinstance(item, dict) and item.get("@type") == "JobPosting" and item.get("title"):
                    return item
        if isinstance(d, dict) and d.get("title"):
            return d
    return None


def _from_detail(card: dict, d: dict) -> FoundPosting:
    desc = strip_html(d.get("description") or "")
    locs = d.get("jobLocation") or []
    if isinstance(locs, dict):
        locs = [locs]
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
        description=desc,
        posted_date=posted,
        deadline=valid or _next_occurrence(card["expires"]),
    )


def _run_stage(session, keywords: list[str], seen: set[str],
               out: list[FoundPosting], quota: int, delay: float,
               category: str = "0", phd_mode: bool = False) -> bool:
    """Returns False if SourceBlocked was hit."""
    details = 0
    for kw in keywords:
        if details >= quota:
            break
        try:
            r = polite_get(session, SEARCH_URL, params={
                "keywords": kw, "location": "", "distance": "0",
                "category": category})
        except SourceBlocked:
            return False
        except (Timeout, ConnectionError):
            time.sleep(delay)
            continue
        time.sleep(delay)
        p = _CardParser()
        p.feed(r.text)
        for card in p.cards:
            if card["id"] in seen:
                continue
            seen.add(card["id"])
            if not _title_matches(card["title"] + " " + card["dept"], phd_mode=phd_mode):
                continue
            if details >= quota:
                break
            try:
                dr = polite_get(session, BASE + card["slug"])
            except SourceBlocked:
                return False
            except (Timeout, ConnectionError):
                time.sleep(delay)
                continue
            details += 1
            d = _parse_detail(dr.text)
            if d:
                out.append(_from_detail(card, d))
            time.sleep(delay)
    return True


def search(session, cfg: dict) -> list[FoundPosting]:
    out: list[FoundPosting] = []
    seen: set[str] = set()
    delay = float(cfg.get("delay_seconds", 1.5))
    max_details = int(cfg.get("max_details", 50))
    phd_quota = int(cfg.get("phd_quota", max(20, max_details // 2)))
    gen_quota = max(10, max_details - phd_quota)

    phd_kws = cfg.get("phd_keywords", DEFAULT_PHD_KEYWORDS)
    gen_kws = cfg.get("keywords", [])

    # Stage 1: Arts & Humanities PhD studentships first (category 0700 + all categories)
    ok = _run_stage(session, phd_kws, seen, out, phd_quota, delay,
                    category="0", phd_mode=True)
    if not ok:
        return out
    # Stage 2: General artistic academic vacancies
    _run_stage(session, gen_kws, seen, out, gen_quota, delay,
               category="0", phd_mode=False)
    return out
