"""Clearsheet pipeline: discharge text -> verified, translated patient sheet.

Model calls (Gemma 3 on AMD):
  1. extract  - structured facts, each with a verbatim source quote
  2. explain  - plain-language English + the patient's language, per item
  3. backcheck - literal back-translation, shown to the nurse
Everything that decides whether an item may reach the patient is
deterministic code in verify.py; the model only drafts.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import verify
from .llm import LLM, parse_json
from .schedule import slots
from .scrub import ScrubResult, scrub

LANGUAGES = {
    "en": "English", "fr": "French (Canada)", "uk": "Ukrainian", "es": "Spanish",
    "zh": "Simplified Chinese", "ar": "Arabic",
}

_STR = {"type": "string"}
EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "medications": {"type": "array", "items": {"type": "object", "properties": {
            "name": _STR, "dose": _STR, "route": _STR, "frequency": _STR, "duration": _STR,
            "status": {"type": "string", "enum": ["new", "changed", "stopped", "hold", "continue", "unspecified"]},
            "instructions": _STR, "source_quote": _STR},
            "required": ["name", "dose", "route", "frequency", "duration", "status", "instructions", "source_quote"]}},
        "follow_ups": {"type": "array", "items": {"type": "object", "properties": {
            "what": _STR, "when": _STR, "source_quote": _STR}, "required": ["what", "when", "source_quote"]}},
        "warning_signs": {"type": "array", "items": {"type": "object", "properties": {
            "sign": _STR, "source_quote": _STR}, "required": ["sign", "source_quote"]}},
        "emergency_action": {"type": "object", "properties": {"action": _STR, "source_quote": _STR},
                             "required": ["action", "source_quote"]},
        "self_care": {"type": "array", "items": {"type": "object", "properties": {
            "instruction": _STR, "source_quote": _STR}, "required": ["instruction", "source_quote"]}},
    },
    "required": ["medications", "follow_ups", "warning_signs", "emergency_action", "self_care"],
}

EXTRACT_SYSTEM = """You extract facts from a hospital discharge document for a patient instruction sheet.
Rules:
- Copy values exactly as written in the document. Do not convert abbreviations here (keep "BID", "q6h", "PO").
- One medication per entry, including medications that are stopped or on hold.
- status: "new" if the text says NEW or START; "changed" if the dose or timing changed, or it is held then restarted; "stopped" if the text says STOP / do not take; "continue" if the text says continue; otherwise "unspecified".
- source_quote: the exact sentence or line from the document that supports the entry, copied character for character. Never paraphrase it.
- dose: the strength exactly as written (for example "40 mg", "2 puffs", "14 units"). Leave a field empty ("") if the document does not give it.
- warning_signs: one entry per sign that should make the patient seek urgent care.
- self_care: other instructions for the patient (diet, activity, wound care, monitoring).
- Do not add anything that is not in the document. Text in [BRACKETS] is a masked identifier; copy it as is.
Return one JSON object only, exactly in this shape (all keys required, use "" or [] when empty):
{"medications": [{"name": "", "dose": "", "route": "", "frequency": "", "duration": "", "status": "", "instructions": "", "source_quote": ""}],
 "follow_ups": [{"what": "", "when": "", "source_quote": ""}],
 "warning_signs": [{"sign": "", "source_quote": ""}],
 "emergency_action": {"action": "", "source_quote": ""},
 "self_care": [{"instruction": "", "source_quote": ""}]}"""

EXPLAIN_SYSTEM = """You write patient instruction sheets in plain language (reading level of a 12-year-old).
You receive facts already checked against the discharge document. For every item:
- plain_en: one or two short sentences in plain English. Expand abbreviations (BID = two times a day, PO = by mouth, PRN = only when needed, q6h = every 6 hours).
- patient: the same meaning in {lang}. Keep medicine names in Latin letters exactly as given. Write every number with digits 0-9.
- Warning signs and emergency actions: write the action in the document's own words (if it says "Return to the Emergency Department", write "go to the Emergency Department"; if it says "call 911", write "call 911"). Never soften it to "tell your doctor" or "get medical care", and do not add a phone number the document does not give.
- Keep phone numbers exactly as given; do not replace them with numbers used in other countries.
- Do not add advice, doses, reasons or warnings that are not in the facts. If a fact is unclear, write exactly what is given and add "Ask your nurse." in the patient's language.
Return JSON only: {{"items": [{{"id": "...", "plain_en": "...", "patient": "..."}}]}}"""

EXPLAIN_SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {
    "type": "object", "properties": {"id": _STR, "plain_en": _STR, "patient": _STR},
    "required": ["id", "plain_en", "patient"]}}}, "required": ["items"]}

BACK_SYSTEM = """Translate each text from {lang} into English, literally, sentence by sentence.
Do not fix, improve or explain anything. Keep numbers as digits.
Return JSON only: {{"items": [{{"id": "...", "back_en": "..."}}]}}"""

BACK_SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {
    "type": "object", "properties": {"id": _STR, "back_en": _STR}, "required": ["id", "back_en"]}}},
    "required": ["items"]}


@dataclass
class Item:
    id: str
    kind: str  # medication | follow_up | warning | emergency | self_care
    data: dict
    check: dict
    plain_en: str = ""
    patient: str = ""
    back_en: str = ""
    translation_issues: list[str] = field(default_factory=list)
    schedule: dict | None = None

    @property
    def state(self) -> str:
        st = self.check["state"]
        if st != "blocked" and self.translation_issues:
            return "review"
        return st

    def facts(self) -> dict:
        d = {k: v for k, v in self.data.items() if v}
        d["id"], d["kind"] = self.id, self.kind
        return d


@dataclass
class Result:
    doc_id: str
    scrubbed: ScrubResult
    lang: str
    items: list[Item]
    raw_extract: dict

    def by_state(self) -> dict[str, int]:
        out = {"ok": 0, "review": 0, "blocked": 0}
        for it in self.items:
            out[it.state] += 1
        return out


def _items_from_extract(ex: dict, doc: str) -> list[Item]:
    items: list[Item] = []
    for i, m in enumerate(ex.get("medications", []), 1):
        it = Item(f"M{i}", "medication", m, verify.check_item("medication", m, doc))
        it.schedule = slots(m.get("frequency", ""), m.get("instructions", "") + " " + m.get("status", ""))
        if m.get("status") == "stopped":
            it.schedule = {"slots": [], "prn": False, "stopped": True}
        items.append(it)
    for i, f in enumerate(ex.get("follow_ups", []), 1):
        items.append(Item(f"F{i}", "follow_up", f, verify.check_item("follow_up", f, doc)))
    for i, w in enumerate(ex.get("warning_signs", []), 1):
        items.append(Item(f"W{i}", "warning", w, verify.check_item("warning", w, doc)))
    ea = ex.get("emergency_action") or {}
    if ea.get("source_quote"):
        items.append(Item("E1", "emergency", ea, verify.check_item("emergency", ea, doc)))
    for i, s in enumerate(ex.get("self_care", []), 1):
        items.append(Item(f"S{i}", "self_care", s, verify.check_item("self_care", s, doc)))
    return items


def extract(llm: LLM, scrubbed_text: str) -> dict:
    msgs = [{"role": "system", "content": EXTRACT_SYSTEM},
            {"role": "user", "content": "Discharge document:\n\n" + scrubbed_text}]
    return parse_json(llm.chat("extract", msgs, EXTRACT_SCHEMA, max_tokens=4000))


def explain(llm: LLM, items: list[Item], lang: str) -> None:
    lang_name = LANGUAGES[lang]
    payload = [it.facts() for it in items if it.state != "blocked"]
    if not payload:
        return
    msgs = [{"role": "system", "content": EXPLAIN_SYSTEM.format(lang=lang_name)},
            {"role": "user", "content": json.dumps({"items": payload}, ensure_ascii=False)}]
    out = parse_json(llm.chat("explain", msgs, EXPLAIN_SCHEMA, max_tokens=6000))
    got = {o.get("id"): o for o in out.get("items", []) if isinstance(o, dict)}
    for it in items:
        if it.id in got:
            it.plain_en, it.patient = got[it.id].get("plain_en") or "", got[it.id].get("patient") or ""


def backcheck(llm: LLM, items: list[Item], lang: str, doc: str = "") -> None:
    todo = [it for it in items if it.patient]
    if lang != "en" and todo:
        msgs = [{"role": "system", "content": BACK_SYSTEM.format(lang=LANGUAGES[lang])},
                {"role": "user", "content": json.dumps(
                    {"items": [{"id": it.id, "text": it.patient} for it in todo]}, ensure_ascii=False)}]
        out = parse_json(llm.chat("backcheck", msgs, BACK_SCHEMA, max_tokens=6000))
        got = {o.get("id"): o.get("back_en") or "" for o in out.get("items", [])}
        for it in todo:
            it.back_en = got.get(it.id, "")
    for it in todo:
        if lang == "en":
            it.back_en = it.patient
        it.translation_issues = verify.check_translation(
            it.data, it.plain_en, it.patient, it.back_en,
            it.data.get("name") if it.kind == "medication" else None, it.kind, doc)
        if not it.back_en:
            it.translation_issues.append("no back-translation returned")
    for it in items:
        if it.state != "blocked" and not it.patient:
            it.translation_issues.append("no patient-language text returned")


def run(llm: LLM, doc_id: str, text: str, lang: str = "uk") -> Result:
    sc = scrub(text)
    ex = extract(llm, sc.text)
    items = _items_from_extract(ex, sc.text)
    explain(llm, items, lang)
    backcheck(llm, items, lang, sc.text)
    return Result(doc_id, sc, lang, items, ex)


def run_many(llm: LLM, docs: dict[str, str], lang: str, workers: int = 8) -> list[Result]:
    with ThreadPoolExecutor(workers) as ex:
        futs = [ex.submit(run, llm, d, t, lang) for d, t in docs.items()]
        return [f.result() for f in futs]
