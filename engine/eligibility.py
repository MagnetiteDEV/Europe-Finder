"""Iranian-applicant eligibility — never inferred, only recorded.

Default for every posting: insufficient_information.
Manual overrides live in eligibility_overrides.json, keyed by posting
key (source::external_id), each with a status and an official source
note. Statuses come from the candidate's search constraints.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT = "insufficient_information"

FA_LABEL = {
    "confirmed_eligible": "واجد شرایط بودن تأیید شده",
    "no_exclusion_found": "منع مشخصی یافت نشد (تأیید قطعی نیست)",
    "clarification_required": "نیازمند استعلام از دانشگاه/کارفرما",
    "restricted": "محدودیت رسمی اعلام شده",
    "insufficient_information": "اطلاعات کافی نیست",
}


def load_overrides(root: Path) -> dict:
    path = root / "eligibility_overrides.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data.get("overrides", {})


def status_for(key: str, overrides: dict) -> tuple[str, str]:
    """Returns (status, source_note). Never guesses from posting text."""
    entry = overrides.get(key)
    if isinstance(entry, dict):
        return (entry.get("status", DEFAULT), entry.get("note", ""))
    if isinstance(entry, str):
        return (entry, "")
    return (DEFAULT, "")
