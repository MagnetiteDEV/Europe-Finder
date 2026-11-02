"""Funding classification — the profile's strict rules, in code.

Categories (policy.json):
  salaried_doctoral_employment / fully_funded_scholarship /
  partially_funded / unfunded / funding_unconfirmed /
  funding_information_unavailable

Rules enforced:
  - "scholarship", "stipend" or "funded" ALONE never proves full funding
    -> funding_unconfirmed.
  - Only explicit "fully funded" / "full funding" -> fully_funded_scholarship.
  - Explicit employment language -> salaried_doctoral_employment.
  - Negative signals -> unfunded (+ red flag).
  - Nothing at all -> funding_information_unavailable.
"""
from __future__ import annotations

import re

SALARIED = [
    "salaried", "employment contract", "employed as", "monthly salary",
    "annual salary", "gross salary", "tv-l", "tvöd", "tv-l e13",
]
FULLY_FUNDED = [
    "fully funded", "full funding", "fully-funded",
]
PARTIAL = [
    "partially funded", "partial funding", "partial scholarship",
]
NEGATIVE = [
    "self-funded", "self funded", "unfunded", "without funding",
    "no funding", "fees apply",
]
UNCONFIRMED_HINTS = [
    "scholarship", "stipend", "funded", "funding", "bursary",
    "grant",
]

FUNDED_OK = {"salaried_doctoral_employment", "fully_funded_scholarship"}

FA_LABEL = {
    "salaried_doctoral_employment": "استخدام دکتری با حقوق",
    "fully_funded_scholarship": "بورسیه کامل تأییدشده",
    "partially_funded": "تأمین مالی ناقص",
    "unfunded": "بدون تأمین مالی",
    "funding_unconfirmed": "تأمین مالی نیازمند تأیید",
    "funding_information_unavailable": "اطلاعات مالی نامشخص",
}


def _has(text: str, phrases: list[str]) -> list[str]:
    return [ph for ph in phrases
            if re.search(r"\b" + re.escape(ph) + r"\b", text)]


def classify_funding(title: str, description: str) -> tuple[str, list[str], list[str]]:
    """Returns (category, evidence_notes, red_flags)."""
    text = f"{title or ''}\n{description or ''}".lower()
    neg = _has(text, NEGATIVE)
    if neg:
        return ("unfunded", [],
                [f"هشدار: بدون تأمین مالی ({', '.join(neg[:2])})"])
    if _has(text, SALARIED):
        ev = _has(text, SALARIED)
        return ("salaried_doctoral_employment",
                [f"شواهد استخدام: {', '.join(ev[:2])}"], [])
    if _has(text, FULLY_FUNDED):
        return ("fully_funded_scholarship", ["«fully funded» صراحتاً ذکر شده"], [])
    if _has(text, PARTIAL):
        return ("partially_funded", [], [])
    if _has(text, UNCONFIRMED_HINTS):
        hints = _has(text, UNCONFIRMED_HINTS)
        return ("funding_unconfirmed",
                [f"اشاره بدون جزئیات کافی: {', '.join(hints[:2])} — به‌تنهایی «fully funded» محسوب نمی‌شود"],
                [])
    return ("funding_information_unavailable", [], [])
