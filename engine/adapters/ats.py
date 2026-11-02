"""University ATS adapters — the coverage engine.

European universities publish vacancies through their own career
pages, which are usually backed by an ATS with a public, keyless
JSON endpoint (the page itself fetches from it). Each tenant in
tenants.json records the verified endpoint; these fetchers speak
each ATS dialect and normalize to FoundPosting.

Supported: Workday (POST), Greenhouse, Lever, Ashby (GET).
SAP SuccessFactors / Oracle / bespoke portals are recorded as
"custom" in the registry and skipped here — they need per-site
scraping, which is v2 work.
"""
from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser

from ..http import SourceBlocked, polite_get, polite_post
from . import FoundPosting


class _Stripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data):
        self.parts.append(data)

    def text(self) -> str:
        return html.unescape(" ".join(" ".join(self.parts).split()))


def strip_html(s: str) -> str:
    if not s or "<" not in s:
        return (s or "").strip()
    st = _Stripper()
    try:
        st.feed(s)
    except Exception:
        return re.sub(r"<[^>]+>", " ", s).strip()
    return st.text()


def _post(session, endpoint: str, payload: dict) -> dict:
    r = polite_post(session, endpoint, json=payload)
    return r.json()


def fetch_workday(session, tenant: dict) -> list[FoundPosting]:
    """endpoint: full .../wday/cxs/{tenant}/{site}/jobs URL."""
    endpoint = tenant["endpoint"]
    base = endpoint.split("/wday/cxs/")[0]
    site = endpoint.rstrip("/").rsplit("/", 2)[-2]
    out: list[FoundPosting] = []
    offset, total = 0, None
    while True:
        data = _post(session, endpoint,
                     {"appliedFacets": {}, "limit": 20, "offset": offset,
                      "searchText": ""})
        postings = data.get("jobPostings", [])
        if total is None:
            total = data.get("total", 0)
        for jp in postings:
            ext = jp.get("externalPath", "")
            bullet = " ".join(jp.get("bulletFields", []) or [])
            loc = jp.get("locationsText", "")
            out.append(FoundPosting(
                source="ats:workday",
                external_id=re.sub(r"\D", "", jp.get("jobReqId", "") or ext) or ext,
                title=jp.get("title", ""),
                organization=tenant.get("name", ""),
                city=loc.split(",")[0].strip() if loc else "",
                url=f"{base}/{site}{ext}" if ext.startswith("/") else f"{base}/{site}/{ext}",
                description=bullet,
            ))
        offset += len(postings)
        if not postings or (total is not None and offset >= min(total, 2000)):
            break
    return out


def fetch_greenhouse(session, tenant: dict) -> list[FoundPosting]:
    endpoint = tenant["endpoint"]  # .../v1/boards/{token}/jobs
    r = polite_get(session, endpoint)
    out: list[FoundPosting] = []
    for j in r.json().get("jobs", []):
        loc = j.get("location", {}) or {}
        out.append(FoundPosting(
            source="ats:greenhouse",
            external_id=str(j.get("id", "")),
            title=j.get("title", ""),
            organization=tenant.get("name", ""),
            city=(loc.get("name", "") or "").split(",")[0],
            url=j.get("absolute_url", ""),
            description=strip_html(j.get("content", "")),
            posted_date=(j.get("updated_at", "") or "")[:10],
        ))
    return out


def fetch_lever(session, tenant: dict) -> list[FoundPosting]:
    endpoint = tenant["endpoint"]  # .../v0/postings/{site}?mode=json
    r = polite_get(session, endpoint)
    out: list[FoundPosting] = []
    for j in r.json():
        cats = j.get("categories", {}) or {}
        out.append(FoundPosting(
            source="ats:lever",
            external_id=j.get("id", ""),
            title=j.get("text", ""),
            organization=tenant.get("name", ""),
            city=str(cats.get("location", "") or "").split(",")[0],
            url=j.get("hostedUrl", ""),
            description=strip_html(j.get("description", "")),
            posted_date=(j.get("createdAt", "") or "")[:10],
        ))
    return out


def fetch_ashby(session, tenant: dict) -> list[FoundPosting]:
    endpoint = tenant["endpoint"]  # .../posting-api/job-board/{org}
    r = polite_get(session, endpoint)
    out: list[FoundPosting] = []
    for j in r.json().get("jobs", []):
        out.append(FoundPosting(
            source="ats:ashby",
            external_id=j.get("id", ""),
            title=j.get("title", ""),
            organization=tenant.get("name", ""),
            city=str(j.get("locationName", "") or "").split(",")[0],
            url=j.get("jobUrl", ""),
            description=strip_html(j.get("descriptionHtml", "")),
            posted_date=(j.get("publishedAt", "") or "")[:10],
        ))
    return out


def fetch_varbi(session, tenant: dict) -> list[FoundPosting]:
    """Varbi (Nordic ATS): JSON:API at api.varbi.com/v1/jobs.

    endpoint: https://api.varbi.com/v1/jobs?filter[organization]={id}
    English adverts need Accept-Language: en (default is Swedish).
    """
    base = tenant["endpoint"]
    lang = {"Accept-Language": "en"}  # default adverts are Swedish
    out: list[FoundPosting] = []
    offset, total = 0, None
    while True:
        sep = "&" if "?" in base else "?"
        r = polite_get(session, f"{base}{sep}limit=50&offset={offset}",
                       timeout=25, headers=lang)
        data = r.json()
        if total is None:
            total = (data.get("meta") or {}).get("total", 0)
        items = data.get("data", [])
        for it in items:
            a = it.get("attributes", {}) or {}
            tx = (a.get("translations") or {}).get("texts", {}) or {}
            dates = a.get("dates", {}) or {}
            loc = (a.get("location") or [{}])[0] or {}
            links = it.get("links", {}) or {}
            out.append(FoundPosting(
                source="ats:varbi",
                external_id=str(it.get("id", "")),
                title=tx.get("title", ""),
                organization=(tx.get("organization", "") or "").split(",")[0],
                country=loc.get("country", ""),
                city=tx.get("placement", "") or "",
                url=links.get("ad_rendered", "") or links.get("self", ""),
                description=" ".join(filter(None, [
                    tx.get("profession", ""), tx.get("organization", "")])),
                posted_date=(dates.get("published", "") or "")[:10],
                deadline=(dates.get("deadline", "") or "")[:10],
            ))
        offset += len(items)
        if not items or (total is not None and offset >= total):
            break
    return out


def fetch_wp(session, tenant: dict) -> list[FoundPosting]:
    """WordPress REST 'job' post type (e.g. UAL jobs.arts.ac.uk).

    endpoint: https://host/wp-json/wp/v2/job  (paginated via
    X-WP-TotalPages).
    """
    base = tenant["endpoint"].rstrip("/")
    out: list[FoundPosting] = []
    page, pages = 1, 1
    while page <= pages:
        r = polite_get(session, base,
                       params={"per_page": 100, "page": page, "_fields":
                               "id,date,link,title,content"})
        try:
            pages = int(r.headers.get("X-WP-TotalPages", "1"))
        except ValueError:
            pages = 1
        for j in r.json():
            title = html.unescape(
                ((j.get("title") or {}).get("rendered", "") or ""))
            out.append(FoundPosting(
                source="ats:wp",
                external_id=str(j.get("id", "")),
                title=" ".join(title.split()),
                organization=tenant.get("name", ""),
                country=tenant.get("country", ""),
                city=tenant.get("city", ""),
                url=j.get("link", ""),
                description=strip_html(
                    (j.get("content") or {}).get("rendered", "")),
                posted_date=(j.get("date", "") or "")[:10],
            ))
        page += 1
    return out


def _volcanic_date(s: str) -> str:
    """Volcanic end_date is DD/MM/YYYY; also accept ISO."""
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s or "")
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    s = (s or "")[:10]
    return s if len(s) == 10 and s[4] == "-" else ""


def fetch_volcanic(session, tenant: dict) -> list[FoundPosting]:
    """Volcanic (Glasgow jobs.gla.ac.uk).

    Page 1:  {endpoint}  (/api/v1/jobs.json, no params — ?page=1 hangs
    the server). Pages 2+: /api/v1/jobs/search.json?page=N (from the
    response's own pagination_html).
    """
    base = tenant["endpoint"]
    search_base = base.replace("/jobs.json", "/jobs/search.json")
    out: list[FoundPosting] = []
    page = 1
    while True:
        if page == 1:
            data = polite_get(session, base, timeout=45).json()
        else:
            data = polite_get(session, search_base, params={"page": page},
                              timeout=45).json()
        jobs = data.get("jobs", [])
        for j in jobs:
            desc = j.get("clean_description") or strip_html(
                j.get("description", ""))
            end = _volcanic_date(j.get("end_date", ""))
            start = (j.get("start_date", "") or "")[:10]
            # per-posting URL: cached_slug already ends with the job id
            # (verified live: /job/research-associate-6054107 -> 200)
            slug = j.get("cached_slug", "")
            url = (f"{base.rsplit('/api/', 1)[0]}/job/{slug}"
                   if slug else tenant.get("careers_url", ""))
            out.append(FoundPosting(
                source="ats:volcanic",
                external_id=str(j.get("id", "")),
                title=j.get("title") or j.get("job_title", ""),
                organization=tenant.get("name", ""),
                country=tenant.get("country", ""),
                city=str(j.get("job_location", "") or "").split(",")[0],
                url=url,
                description=desc,
                posted_date=start if len(start) == 10 and start[4] == "-" else "",
                deadline=end,
            ))
        pages = data.get("page_count") or 1
        if page >= pages or not jobs:
            break
        page += 1
    return out


def fetch_kuleuven(session, tenant: dict) -> list[FoundPosting]:
    """KU Leuven in-house Elasticsearch filter component.

    POST {endpoint} {"_locale":"en","environment":"production"}.
    Server-fixed pagination: first 15 of ~42 (from/size ignored).
    No per-posting URL is exposed; link falls back to the listing page.
    """
    data = polite_post(session, tenant["endpoint"],
                       json={"_locale": "en", "environment": "production"},
                       timeout=45).json()
    out: list[FoundPosting] = []
    for h in data.get("hits", []):
        src = h.get("_src", h.get("_source", {})) or {}
        post = src.get("posting", {}) or {}
        raw_dl = src.get("applyBefore", "") or ""
        deadline = (f"{raw_dl[:4]}-{raw_dl[4:6]}-{raw_dl[6:8]}"
                    if len(raw_dl) == 8 and raw_dl.isdigit() else "")
        out.append(FoundPosting(
            source="ats:kuleuven",
            external_id=str(src.get("id", h.get("_id", ""))),
            title=post.get("title", ""),
            organization=(src.get("orgUnitDescription", "") or "").split(",")[0],
            country=tenant.get("country", ""),
            city=src.get("city", ""),
            url=tenant.get("careers_url", ""),
            description=" ".join(filter(None, [
                post.get("teaser", ""), src.get("occupation", "")])),
            deadline=deadline,
        ))
    return out


FETCHERS = {
    "workday": fetch_workday,
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "varbi": fetch_varbi,
    "wp": fetch_wp,
    "volcanic": fetch_volcanic,
    "kuleuven": fetch_kuleuven,
}


def load_tenants(path: str) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    return [t for t in data if t.get("verified") and t.get("ats") in FETCHERS]


def search(session, cfg: dict) -> list[FoundPosting]:
    import time
    tenants = load_tenants(cfg.get("tenants_file", "tenants.json"))
    delay = float(cfg.get("delay_seconds", 1.5))
    out: list[FoundPosting] = []
    for t in tenants:
        try:
            out.extend(FETCHERS[t["ats"]](session, t))
        except SourceBlocked:
            break
        except Exception as e:  # one tenant must not kill the run
            print(f"  [ats] {t.get('name')}: skipped ({e})")
        time.sleep(delay)
    return out
