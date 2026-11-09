"""EURAXESS jobs adapter (EU research portal, HTML listing).

Source: https://euraxess.ec.europa.eu/jobs/search
- robots.txt does NOT disallow /jobs/search (only /admin, /core,
  /user and similar paths are off-limits), so a polite read of the
  public listing is allowed.
- There is no public read API: the "API" in EURAXESS docs is for
  institutions to *publish* vacancies, and the host bot-walls
  /api/ paths (403/429 from here). The listing itself is
  server-rendered Drupal HTML, so this adapter parses it.
- Cards use the stable EU Component Library (ECL) classes:
  article.ecl-content-item > h3.ecl-content-block__title >
  a[href=/jobs/<id>] > span (title), the first primary-meta <li>
  holds the organisation, a "Posted on: D Month YYYY" <li> holds
  the date, and ecl-content-block__description holds the text.
- The search form is POST-only (Drupal form_build_id), so we fetch
  the unfiltered newest listing, pages 0..N-1, and let the engine
  matcher filter by subject — the same "fetch wide, filter local"
  approach as the Nature RSS adapter.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from html import unescape

from ..http import SourceBlocked, polite_get
from . import FoundPosting

BASE = "https://euraxess.ec.europa.eu"
SEARCH_URL = BASE + "/jobs/search"
SOURCE = "euraxess"

_ID_RE = re.compile(r"^/jobs/(\d+)$")
_POSTED_RE = re.compile(r"Posted on:\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})")
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}


class _CardParser(HTMLParser):
    """Collects ECL job cards from a /jobs/search page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards: list[dict] = []
        self._cur: dict | None = None
        self._in_title_a = False
        self._in_title_span = False
        self._in_meta_li = False
        self._in_meta_a = False
        self._in_desc = False
        self._in_desc_p = False
        self._buf = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "")
        if tag == "article" and "ecl-content-item" in cls:
            self._cur = {"org": "", "posted": "", "title": "",
                         "url": "", "id": "", "desc": ""}
            return
        if self._cur is None:
            return
        if tag == "li" and "ecl-content-block__primary-meta-item" in cls:
            self._in_meta_li = True
            self._buf = ""
        elif tag == "a" and self._in_meta_li:
            self._in_meta_a = True
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
            txt = self._buf.strip()
            if not self._cur["org"] and txt and "Posted on" not in txt:
                self._cur["org"] = txt
            m = _POSTED_RE.search(txt)
            if m and m.group(2) in _MONTHS:
                self._cur["posted"] = (
                    f"{int(m.group(3)):04d}-{_MONTHS[m.group(2)]:02d}-"
                    f"{int(m.group(1)):02d}")
            self._in_meta_li = False
            self._in_meta_a = False
            self._buf = ""
        elif tag == "a" and self._in_meta_a:
            self._in_meta_a = False
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


def _parse_page(html: str) -> list[FoundPosting]:
    p = _CardParser()
    p.feed(html)
    out: list[FoundPosting] = []
    for c in p.cards:
        out.append(FoundPosting(
            source=SOURCE,
            external_id=c["id"],
            title=" ".join(unescape(c["title"]).split()),
            organization=" ".join(unescape(c["org"]).split()),
            url=c["url"],
            description=" ".join(unescape(c["desc"]).split()),
            posted_date=c["posted"],
        ))
    return out


def search(session, cfg: dict) -> list[FoundPosting]:
    out: list[FoundPosting] = []
    seen: set[str] = set()
    pages = max(1, int(cfg.get("pages", 2)))
    for page in range(pages):
        params = {"page": page} if page else None
        try:
            r = polite_get(session, SEARCH_URL, params=params)
        except SourceBlocked:
            break
        for p in _parse_page(r.text):
            if p.key() not in seen:
                seen.add(p.key())
                out.append(p)
        if len(out) == 0:
            break
    return out
