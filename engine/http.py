"""Polite HTTP helpers shared by all adapters.

Every request identifies itself, respects timeouts, backs off on
server errors, and stops the whole run on 429/403 instead of
hammering the source — the same politeness Dossier documents for
its own fetching.
"""
from __future__ import annotations

import time

import requests
from requests.exceptions import ConnectionError, Timeout

USER_AGENT = "PhDSearchEngine/1.0 (personal academic research; polite crawler)"
DEFAULT_TIMEOUT = 20


class SourceBlocked(Exception):
    """Raised on 429/403: the source asked us to stop. The run aborts
    for that source instead of retrying around the block."""


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, application/rss+xml, application/xml, text/html, */*",
        }
    )
    return s


def _sleep(attempt: int, base: float) -> None:
    time.sleep(base * (2**attempt))


def polite_get(session, url, params=None, timeout=DEFAULT_TIMEOUT,
               retries=3, base_delay=1.5, headers=None):
    last = None
    for attempt in range(retries + 1):
        try:
            r = session.get(url, params=params, timeout=timeout,
                            headers=headers)
        except (Timeout, ConnectionError):
            if attempt < retries:
                _sleep(attempt, base_delay)
                continue
            raise
        last = r
        if r.status_code in (429, 403):
            raise SourceBlocked(f"{r.status_code} from {url}")
        if r.status_code >= 500 and attempt < retries:
            _sleep(attempt, base_delay)
            continue
        r.raise_for_status()
        return r
    last.raise_for_status()


def polite_post(session, url, json=None, timeout=DEFAULT_TIMEOUT,
                retries=3, base_delay=1.5):
    last = None
    for attempt in range(retries + 1):
        try:
            r = session.post(url, json=json, timeout=timeout)
        except (Timeout, ConnectionError):
            if attempt < retries:
                _sleep(attempt, base_delay)
                continue
            raise
        last = r
        if r.status_code in (429, 403):
            raise SourceBlocked(f"{r.status_code} from {url}")
        if r.status_code >= 500 and attempt < retries:
            _sleep(attempt, base_delay)
            continue
        r.raise_for_status()
        return r
