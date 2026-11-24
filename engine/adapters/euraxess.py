"""EURAXESS jobs adapter (EU research portal, HTML listing).

Upgraded in v2.9.3 for PhD discovery in Arts, Design, Fashion, History &
Material Culture:
  1. Queries EURAXESS with First Stage Researcher (R1 = PhD) facet
     (`f[0]=job_research_profile:1044`) + Arts/Humanities/Design keywords
     AND the Arts research-field facet (`f[0]=job_research_field:373`),
     with polite delays between requests.
  2. Also fetches N unfiltered newest pages as a safety net so changes
     to Drupal facet IDs never break the source.
  3. Extracts Application Deadline + Country from each ECL job card.
"""
from __future__ import annotations

import re
import time
from html import unescape
from html.parser import HTMLParser

from requests.exceptions import ConnectionError, Timeout

from ..extract import extract_country, extract_deadline
from ..http import SourceBlocked, polite_get
from . import FoundPosting

BASE = "https://euraxess.ec.europa.eu"
SEARCH_URL = BASE + "/jobs/search"
SOURCE = "euraxess"

_ID_RE = re.compile(r"^/jobs/(\d+)$")
_POSTED_RE = re.compile(r"Posted on:\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})")
_DEADLINE_RE = re.compile(
    r"(?:Application\s+Deadline|Deadline):\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
    re.I)
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}
_MONTHS.update({m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul",
     "Aug", "Sep", "Oct", "Nov", "Dec"])})

DEFAULT_PHD_QUERIES = [
    {"keywords": "fashion OR textile OR costume", "f[0]": "job_research_profile:1044"},
    {"keywords": "art history OR visual culture OR curatorial", "f[0]": "job_research_profile:1044"},
    {"keywords": "design research OR artistic research", "f[0]": "job_research_profile:1044"},
    {"keywords": "museum OR cultural heritage OR material culture", "f[0]": "job_research_profile:1044"},
    {"f[0]": "job_research_field:373", "f[1]": "job_research_profile:1044"},  # Arts + R1 PhD
    {"f[0]": "job_research_field:373"},  # Arts (all stages)
]


class _CardParser(HTMLParser):
    """Collects ECL job cards from a /jobs/search page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards: list[dict] = []
        self._cur: dict | None = None
        self._in_title_a = False
        self._in_title_span = False
        self._in_meta_li = False
        self._in_desc = False
        self._in_desc_p = False
        self._buf = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "")
        if tag == "article" and "ecl-content-item" in cls:
            self._cur = {"org": "", "posted": "", "deadline": "", "country_txt": "",
                         "title": "", "url": "", "id": "", "desc": ""}
            return
        if self._cur is None:
            return
        if tag == "li" and ("ecl-content-block__primary-meta-item" in cls
                            or "ecl-content-block__secondary-meta-item" in cls):
            self._in_meta_li = True
            self._buf = ""
        elif tag == "a" and "ecl-link--standalone" in cls:
            m = _ID_RE.match(a.get("href", ""))
            if m:
                self._cur["id"] = m.group(1)
                self._cur["url"] = BASE + a["href"]
                self._in_title_a = True
        elif tag == "span" and self._in_title_a:
            self._in_title_span = True
            self._buf = ""
        elif tag == "div" and "ecl-content-block__description" in cls:
            self._in_desc = True
        elif tag == "p" and self._in_desc:
            self._in_desc_p = True
            self._buf = ""

    def handle_endtag(self, tag):
        if self._cur is None:
            return
        if tag == "article":
            if self._cur["id"] and self._cur["title"]:
                self.cards.append(self._cur)
            self._cur = None
        elif tag == "li" and self._in_meta_li:
            txt = " ".join(self._buf.split())
            if txt:
                pm = _POSTED_RE.search(txt)
                dm = _DEADLINE_RE.search(txt)
                if pm and pm.group(2) in _MONTHS:
                    self._cur["posted"] = (
                        f"{int(pm.group(3)):04d}-{_MONTHS[pm.group(2)]:02d}-"
                        f"{int(pm.group(1)):02d}")
                elif dm and dm.group(2) in _MONTHS:
                    self._cur["deadline"] = (
                        f"{int(dm.group(3)):04d}-{_MONTHS[dm.group(2)]:02d}-"
                        f"{int(dm.group(1)):02d}")
                elif not self._cur["org"] and "Posted on" not in txt and "Deadline" not in txt:
                    self._cur["org"] = txt
                else:
                    self._cur["country_txt"] += " " + txt
            self._in_meta_li = False
            self._buf = ""
        elif tag == "span" and self._in_title_span:
            self._cur["title"] = self._buf.strip()
            self._in_title_span = False
            self._buf = ""
        elif tag == "a" and self._in_title_a:
            self._in_title_a = False
        elif tag == "p" and self._in_desc_p:
            self._cur["desc"] += self._buf.strip() + " "
            self._in_desc_p = False
            self._buf = ""
        elif tag == "div" and self._in_desc:
            self._in_desc = False

    def handle_data(self, data):
        if self._cur is None:
            return
        if self._in_title_span or self._in_meta_li or self._in_desc_p:
            self._buf += data


def _parse_page(html_text: str, force_phd: bool = False) -> list[FoundPosting]:
    p = _CardParser()
    p.feed(html_text)
    out: list[FoundPosting] = []
    for c in p.cards:
        title = " ".join(unescape(c["title"]).split())
        org = " ".join(unescape(c["org"]).split())
        desc = " ".join(unescape(c["desc"]).split())
        cc = extract_country(c["country_txt"] + " " + org + " " + desc, "")
        dl = c["deadline"] or extract_deadline(desc)
        post = FoundPosting(
            source=SOURCE,
            external_id=c["id"],
            title=title,
            organization=org,
            country=cc,
            url=c["url"],
            description=desc,
            posted_date=c["posted"],
            deadline=dl,
        )
        if force_phd:
            post.kind = "phd"
            post._kind_fixed = True
        out.append(post)
    return out


def search(session, cfg: dict) -> list[FoundPosting]:
    out: list[FoundPosting] = []
    seen: set[str] = set()
    delay = float(cfg.get("delay_seconds", 1.5))
    pages = max(1, int(cfg.get("pages", 3)))
    queries = cfg.get("phd_queries", DEFAULT_PHD_QUERIES)

    # Stage 1: Targeted artistic + R1 PhD queries
    for qparams in queries:
        is_r1 = any("job_research_profile:1044" in str(v) for v in qparams.values())
        for page in range(2):
            params = dict(qparams)
            if page:
                params["page"] = page
            try:
                r = polite_get(session, SEARCH_URL, params=params, timeout=25)
            except SourceBlocked:
                return out
            except (Timeout, ConnectionError):
                break
            cards = _parse_page(r.text, force_phd=is_r1)
            added = 0
            for p in cards:
                if p.key() not in seen:
                    seen.add(p.key())
                    out.append(p)
                    added += 1
            time.sleep(delay)
            if not cards or added == 0:
                break

    # Stage 2: Unfiltered newest safety net
    for page in range(pages):
        params = {"page": page} if page else None
        try:
            r = polite_get(session, SEARCH_URL, params=params, timeout=25)
        except SourceBlocked:
            break
        except (Timeout, ConnectionError):
            break
        cards = _parse_page(r.text, force_phd=False)
        for p in cards:
            if p.key() not in seen:
                seen.add(p.key())
                out.append(p)
        time.sleep(delay)
        if not cards:
            break
    return out
