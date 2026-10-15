"""Deterministic checks. No model is involved in any decision made here.

1. Grounding: every extracted item carries a source_quote; the quote must be
   found in the (scrubbed) discharge text, and every number in the item's
   fields must appear inside that quote.
2. Risk: high-alert medicines (ISMP categories), medication changes and
   stops always go to a nurse, whatever the model says.
3. Translation: the numbers a patient reads must match the source.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
# a number (or range / ratio) bound to its unit: "40 mg", "875/125 mg", "1-2 weeks", "q6h" -> "6h"
QTY_RE = re.compile(r"\d+(?:[.,]\d+)?(?:\s*[-/]\s*\d+(?:[.,]\d+)?)?\s*[a-zA-Z\u00b5%]+")

# ISMP high-alert medication classes, community/ambulatory list (subset).
HIGH_ALERT = {
    "anticoagulant": ["apixaban", "rivaroxaban", "dabigatran", "edoxaban", "warfarin",
                      "enoxaparin", "heparin", "dalteparin", "tinzaparin", "fondaparinux"],
    "insulin": ["insulin"],
    "opioid": ["oxycodone", "hydromorphone", "morphine", "fentanyl", "codeine", "tramadol",
               "methadone", "tapentadol", "buprenorphine"],
    "oral hypoglycemic (sulfonylurea)": ["glyburide", "gliclazide", "glimepiride"],
    "narrow therapeutic index": ["digoxin", "lithium", "amiodarone", "methotrexate",
                                 "phenytoin", "carbamazepine"],
    "electrolyte": ["potassium chloride"],
    "systemic steroid taper": ["prednisone", "dexamethasone", "methylprednisolone"],
}

STATUS_WORDS = {
    "stopped": ["stop", "discontinue", "do not take", "replaces"],
    "new": ["new", "start"],
    "changed": ["increase", "decrease", "reduce", "hold", "changed", "from", "restart"],
    "hold": ["hold"],
}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("–", "-").replace("—", "-").replace("’", "'")
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def numbers(s: str) -> list[str]:
    s = unicodedata.normalize("NFKC", s or "")
    # Arabic-Indic and Persian digits -> ASCII
    s = s.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789"))
    return [n.replace(",", ".") for n in NUM_RE.findall(s)]


def quote_score(quote: str, doc: str) -> float:
    """1.0 if the quote is a verbatim (normalised) substring of doc, else the
    best fuzzy ratio against same-length windows of the document."""
    q, d = norm(quote), norm(doc)
    if not q:
        return 0.0
    if q in d:
        return 1.0
    words = d.split(" ")
    qn = len(q.split(" "))
    best = 0.0
    for i in range(0, max(1, len(words) - qn + 1)):
        for span in (qn - 1, qn, qn + 1):
            if span <= 0:
                continue
            w = " ".join(words[i:i + span])
            r = difflib.SequenceMatcher(None, q, w).ratio()
            if r > best:
                best = r
    return round(best, 3)


def high_alert_class(name: str) -> str | None:
    n = norm(name)
    for cls, drugs in HIGH_ALERT.items():
        if any(d in n for d in drugs):
            return cls
    return None


def check_item(kind: str, item: dict, doc: str) -> dict:
    """Return {'grounding': float, 'issues': [...], 'risk': [...], 'state': ok|review|blocked}."""
    issues: list[str] = []
    risk: list[str] = []
    quote = item.get("source_quote", "")
    g = quote_score(quote, doc)
    if g < 0.92:
        issues.append(f"source quote not found in the document (match {g:.2f})")
    qnums = set(numbers(quote))
    fields = [v for k, v in item.items() if k not in ("source_quote", "id", "status") and isinstance(v, str)]
    missing = sorted({n for f in fields for n in numbers(f)} - qnums)
    if missing:
        issues.append("numbers not in the source quote: " + ", ".join(missing))
    nq = norm(quote).replace(" ", "")
    unbound = sorted({q for f in fields for q in QTY_RE.findall(norm(f)) if q.replace(" ", "") not in nq})
    if unbound and not missing:
        issues.append("numbers with units not in the source quote: " + ", ".join(unbound))

    if kind == "medication":
        name = item.get("name", "")
        first = norm(name).split(" ")[0] if name else ""
        if first and first not in norm(quote):
            issues.append(f"medicine name '{name}' not in the source quote")
        cls = high_alert_class(name)
        if cls:
            risk.append(f"high-alert medicine: {cls}")
        status = item.get("status", "unspecified")
        if status in ("stopped", "changed", "hold"):
            risk.append(f"medication {status}: confirm with the patient")
        words = STATUS_WORDS.get(status)
        if words and not any(w in norm(quote) for w in words):
            issues.append(f"status '{status}' is not stated in the source quote")
        if "taper" in norm(quote) or "then" in norm(item.get("frequency", "") + " " + item.get("duration", "")):
            risk.append("multi-step schedule: check the dates on the sheet")

    state = "blocked" if any(i.startswith(("source quote", "numbers", "medicine name")) for i in issues) \
        else ("review" if (issues or risk) else "ok")
    return {"grounding": g, "issues": issues, "risk": risk, "state": state}


URGENT_SRC = re.compile(r"emergency|911|\ber\b|urgent|ambulance|go to (the )?hospital|seek (urgent|emergency)", re.I)
SOFT_OUT = re.compile(r"(tell|see|call|contact|talk to|inform) (your |the )?(doctor|gp|physician|nurse|pharmacist)"
                      r"|family doctor|next (visit|appointment)|medical (care|help|attention)|when you can", re.I)
URGENT_OUT = re.compile(r"emergency|911|ambulance|urgent|hospital|\ber\b", re.I)


def urgency_lost(source_quote: str, english: str) -> bool:
    """The source sends the patient to emergency care; the English plain or back-translated text does not."""
    return bool(URGENT_SRC.search(source_quote or "")) and not URGENT_OUT.search(english or "")


def check_translation(item: dict, plain_en: str, patient: str, back_en: str, drug_name: str | None,
                      kind: str = "", doc: str = "") -> list[str]:
    """Numbers the patient reads must be numbers from the source or from the
    English plain version; key dose numbers must survive; the drug name must
    survive the back-translation."""
    problems: list[str] = []
    allowed = set(numbers(item.get("source_quote", ""))) | set(numbers(plain_en))
    src = set(numbers(item.get("source_quote", ""))) | {"1", "2", "3", "4"}  # small counts from "BID", "TID"...
    if kind in ("warning", "emergency"):
        src |= set(numbers(doc))  # the emergency number may sit in the document's lead-in sentence
    added = sorted(set(numbers(plain_en)) - src)
    if added:
        problems.append("plain text adds numbers not in the source: " + ", ".join(added))
    pnums = set(numbers(patient))
    extra = sorted(pnums - allowed)
    if extra:
        problems.append("translation adds numbers not in the source: " + ", ".join(extra))
    dose_nums = set(numbers(item.get("dose", "")))
    lost = sorted(dose_nums - pnums)
    if lost:
        problems.append("dose number missing in translation: " + ", ".join(lost))
    if kind == "warning":
        # a sign listed under the emergency heading needs no action of its own, but it must not be softened
        for label, text in (("plain text", plain_en), ("translation", back_en)):
            if URGENT_SRC.search(item.get("source_quote", "")) and SOFT_OUT.search(text or "") and not URGENT_OUT.search(text or ""):
                problems.append(f"urgency weaker than the source: the {label} softens the emergency action")
                break
    elif kind == "emergency":
        if urgency_lost(item.get("source_quote", ""), plain_en):
            problems.append("urgency weaker than the source: the plain text drops the emergency action")
        elif urgency_lost(item.get("source_quote", ""), back_en):
            problems.append("urgency weaker than the source: the translation drops the emergency action")
    if drug_name:
        first = norm(drug_name).split(" ")[0]
        if first and first not in norm(patient) and first not in norm(back_en):
            problems.append(f"medicine name '{drug_name}' lost in translation")
    return problems
