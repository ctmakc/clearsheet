"""Turn a frequency string copied from the discharge text into daily slots.

Deterministic. Anything it cannot parse comes back as None and the sheet
shows "see instructions" instead of guessing.
"""
from __future__ import annotations

import re

SLOTS = ["morning", "midday", "evening", "bedtime"]


def slots(frequency: str, extra: str = "") -> dict | None:
    f = " " + (frequency or "").lower() + " " + (extra or "").lower() + " "
    prn = bool(re.search(r"\bprn\b|as needed|when needed|if needed", f))
    if re.search(r"\bstop\b|do not take", f):
        return {"slots": [], "prn": False, "stopped": True}
    s: list[str] | None = None
    if re.search(r"\bqid\b|four times|q6h|every 6 hours", f):
        s = ["morning", "midday", "evening", "bedtime"]
    elif re.search(r"\btid\b|three times|q8h|every 8 hours", f):
        s = ["morning", "midday", "bedtime"] if "q8h" in f or "8 hours" in f else ["morning", "midday", "evening"]
    elif re.search(r"\bbid\b|twice|two times|q12h|every 12 hours", f):
        s = ["morning", "evening"]
    elif re.search(r"\bqhs\b|at bedtime|at night|before bed", f):
        s = ["bedtime"]
    elif re.search(r"in the evening|with supper|at supper", f):
        s = ["evening"]
    elif re.search(r"once daily|\bdaily\b|once a day|every day|\bqd\b|once tomorrow|in the morning|with breakfast", f):
        s = ["morning"]
    elif re.search(r"q4h|q4-6h|every 4", f):
        s = []  # interval dosing; only meaningful as PRN on a sheet
        prn = True
    if s is None and not prn:
        return None
    if prn and s and re.search(r"q4h|q4-6h|q6h|q8h", f) and "scheduled" not in f:
        s = []  # PRN interval medicines are not placed in fixed slots
    return {"slots": s or [], "prn": prn, "stopped": False}
