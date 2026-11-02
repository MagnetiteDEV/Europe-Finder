"""PhD Search Engine v1 — adapter-based opportunity aggregator.

Architecture borrows Dossier's job-search pattern: every source is an
adapter exposing search(); postings are normalized to FoundPosting,
de-duplicated, scored against the discipline taxonomy, and exported
for the offline PWA.
"""
