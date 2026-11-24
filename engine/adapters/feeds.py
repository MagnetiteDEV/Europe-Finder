"""Feed adapters: Cumulus Association job listings (RSS 2.0) and
ArtHist.net announcements (Atom).

Cumulus (https://cumulusassociation.org/member-portal/job-listings/feed/):
design-education job board (PhD, faculty, postdoc). The feed carries
title/link/date only — the summary is boilerplate — so each entry
gets one detail fetch for the organisation ("Organization" widget)
and the "Apply by" deadline. The detail page's <main> is empty; the
real vacancy text lives on the employer's site, so the description
stays thin (organisation + department) and the matcher scores on
title + organisation. robots.txt: empty Disallow.

ArtHist.net (https://arthist.net/rss.xml): art-history forum feed
(20 entries, title/link/date only). Only JOB: / STIP: announcements
are kept; the rest (CONF:, CFP:, REV:, ...) are events and calls,
not positions. Each keeper gets one detail fetch for the full text
(<div id="body">). robots.txt: Allow / with Crawl-delay: 10 — the
adapter honours the configured delay between requests, and never
touches the disallowed /Search*.html pages. STIP: items (fellowships
/ grants) are kind "scholarship"; JOB: items go through detect_kind.
"""
from __future__ import annotations

import re
import time
from html.parser import HTMLParser

import feedparser
from requests.exceptions import ConnectionError, Timeout

from ..extract import clean_plain_text, extract_deadline
from ..http import SourceBlocked, polite_get
from . import FoundPosting
from .ats import strip_html

CUMULUS_FEED = "https://cumulusassociation.org/member-portal/job-listings/feed/"
ARTHIST_FEED = "https://arthist.net/rss.xml"

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}
_MONTHS.update({m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul",
     "Aug", "Sep", "Oct", "Nov", "Dec"])})

_CUMULUS_DEADLINE_RE = re.compile(
    r"Apply by\s+([A-Za-z]+)\.?\s+(\d{1,2}),\s+(\d{4})")
_CUMULUS_ORG_RE = re.compile(r"<h4>Organization</h4>(.*?)</ul>", re.S)
_CUMULUS_ID_RE = re.compile(r"[?&]p=(\d+)")
_ARTHIST_ID_RE = re.compile(r"/archive/(\d+)")
_ARTHIST_PREFIX_RE = re.compile(r"^(JOB|STIP)\s*:\s*", re.I)


def _iso_date(parsed) -> str:
    if not parsed:
        return ""
    return f"{parsed.tm_year:04d}-{parsed.tm_mon:02d}-{parsed.tm_mday:02d}"


def _parse_cumulus_detail(html_text: str) -> dict:
    """Organisation + department + deadline from a job-listing page."""
    org, dept, deadline = "", "", ""
    m = _CUMULUS_DEADLINE_RE.search(html_text)
    if m:
        mon = _MONTHS.get(m.group(1).rstrip("."))
        if mon:
            try:
                from datetime import date
                deadline = date(int(m.group(3)), mon,
                                int(m.group(2))).isoformat()
            except ValueError:
                deadline = ""
    om = _CUMULUS_ORG_RE.search(html_text)
    if om:
        block = om.group(1)
        sm = re.search(r"<strong[^>]*>(.*?)</strong>", block, re.S)
        if sm:
            org = strip_html(sm.group(1))
            rest = block[sm.end():]
            rest = re.split(r"<br|<a[\s>]", rest, maxsplit=1)[0]
            dept = strip_html(rest)
    return {"org": org, "dept": dept, "deadline": deadline}


class _BodyParser(HTMLParser):
    """Text inside <div id='body'> on an ArtHist archive page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._depth = 0
        self._in_body = False

    def handle_starttag(self, tag, attrs):
        if tag == "div" and dict(attrs).get("id") == "body":
            self._in_body = True
            self._depth = 1
            return
        if self._in_body and tag == "div":
            self._depth += 1

    def handle_endtag(self, tag):
        if self._in_body and tag == "div":
            self._depth -= 1
            if self._depth <= 0:
                self._in_body = False

    def handle_data(self, data):
        if self._in_body:
            self.parts.append(data)

    def text(self) -> str:
        return " ".join(" ".join(self.parts).split())


def search_cumulus(session, cfg: dict) -> list[FoundPosting]:
    out: list[FoundPosting] = []
    delay = float(cfg.get("delay_seconds", 1.5))
    cap = int(cfg.get("max_items", 20))
    try:
        r = polite_get(session, CUMULUS_FEED)
    except SourceBlocked:
        return out
    feed = feedparser.parse(r.content)
    for e in feed.entries[:cap]:
        link = e.get("link", "")
        m = _CUMULUS_ID_RE.search(e.get("id", "") or link)
        if not m:
            continue
        org, dept, deadline = "", "", ""
        try:
            time.sleep(delay)
            dr = polite_get(session, link)
            d = _parse_cumulus_detail(dr.text)
            org, dept, deadline = d["org"], d["dept"], d["deadline"]
        except SourceBlocked:
            break
        except (Timeout, ConnectionError):
            pass  # keep the feed-level item without detail
        desc = " ".join(x for x in [org, dept] if x)
        out.append(FoundPosting(
            source="cumulus",
            external_id=m.group(1),
            title=" ".join((e.get("title") or "").split()),
            organization=org,
            url=link,
            description=desc,
            posted_date=_iso_date(e.get("published_parsed")),
            deadline=deadline,
        ))
    return out


def search_arthist(session, cfg: dict) -> list[FoundPosting]:
    out: list[FoundPosting] = []
    # robots.txt Crawl-delay: 10 — honour it between every request.
    delay = float(cfg.get("delay_seconds", 10))
    try:
        r = polite_get(session, ARTHIST_FEED)
    except SourceBlocked:
        return out
    feed = feedparser.parse(r.content)
    for e in feed.entries:
        title = (e.get("title") or "").strip()
        pm = _ARTHIST_PREFIX_RE.match(title)
        if not pm:
            continue
        kind_prefix = pm.group(1).upper()
        link = e.get("link", "")
        m = _ARTHIST_ID_RE.search(link)
        if not m:
            continue
        clean_title = " ".join(_ARTHIST_PREFIX_RE.sub("", title).split())
        body, deadline = "", ""
        try:
            time.sleep(delay)
            dr = polite_get(session, link)
            p = _BodyParser()
            p.feed(dr.text)
            body = clean_plain_text(p.text())[:8000]
            deadline = extract_deadline(body)
        except SourceBlocked:
            break
        except (Timeout, ConnectionError):
            pass  # keep the title-only item
        post = FoundPosting(
            source="arthist",
            external_id=m.group(1),
            title=clean_title,
            url=link,
            description=body,
            posted_date=_iso_date(e.get("published_parsed")),
            deadline=deadline,
        )
        if kind_prefix == "STIP":
            # fellowships / grants are funding routes, not jobs
            post.kind = "scholarship"
            post._kind_fixed = True
        out.append(post)
    return out
