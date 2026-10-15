"""Local identifier masking.

Runs before any text leaves the machine. Replaces direct identifiers with
stable placeholders ([NAME_1], [MRN_1], ...) and keeps the mapping locally so
the final printed sheet can show the real name again. Deterministic regex
rules: it does not need a model and never calls one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Labelled fields: the value after the label is an identifier.
_LABELLED = [
    ("NAME", r"(?:Patient(?: name)?|Name|Parent/guardian)\s*:\s*"
             r"([A-Z][\w'\-À-ſ]+(?:\s+\"?[A-Z][\w'\-À-ſ\"]+){0,3})"),
    ("MRN", r"(?:MRN|Medical record #|Chart)\s*:?\s*([A-Z]{0,4}-?[\d][\d\-]{4,})"),
    ("HEALTH_CARD", r"Health Card\s*:\s*([\w\-]{6,})"),
    ("DOB", r"(?:DOB|Date of birth|Born)\s*:?\s*(\d{4}-\d{2}-\d{2})"),
    ("ADDRESS", r"Address\s*:\s*([^\n]+)"),
]
# Free-standing patterns.
_FREE = [
    ("EMAIL", r"[\w.+-]+@[\w-]+\.[\w.]+"),
    ("PHONE", r"\(?\b\d{3}\)?[\s.\-]?\d{3}[\s.\-]\d{4}\b"),
    ("POSTAL", r"\b[A-Z]\d[A-Z]\s?\d[A-Z]\d\b"),
]


@dataclass
class ScrubResult:
    text: str
    mapping: dict[str, str] = field(default_factory=dict)  # placeholder -> original

    def restore(self, s: str) -> str:
        for ph, orig in self.mapping.items():
            s = s.replace(ph, orig)
        return s

    @property
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for ph in self.mapping:
            kind = ph.strip("[]").rsplit("_", 1)[0]
            out[kind] = out.get(kind, 0) + 1
        return out


def scrub(text: str) -> ScrubResult:
    mapping: dict[str, str] = {}
    reverse: dict[tuple[str, str], str] = {}

    def ph_for(kind: str, value: str) -> str:
        key = (kind, value)
        if key not in reverse:
            n = sum(1 for k in reverse if k[0] == kind) + 1
            reverse[key] = f"[{kind}_{n}]"
            mapping[reverse[key]] = value
        return reverse[key]

    out = text
    names: list[str] = []
    for kind, pat in _LABELLED:
        for m in re.finditer(pat, out):
            val = m.group(1).strip()
            if kind == "NAME":
                # Stop at the next field label on the same line.
                val = re.split(r"\s{2,}|\s+(?:MRN|DOB|Phone|Tel|Email|Chart)\b", val)[0].strip()
                names.append(val)
            ph_for(kind, val)
    for (kind, val), ph in sorted(reverse.items(), key=lambda kv: -len(kv[0][1])):
        out = out.replace(val, ph)
    # First names and surnames used alone later in the text ("Bring Mila back").
    for full in names:
        for part in re.findall(r"[A-Z][\w'\-À-ſ]{2,}", full.replace('"', " ")):
            if re.search(rf"\b{re.escape(part)}\b", out):
                out = re.sub(rf"\b{re.escape(part)}\b", ph_for("NAME", part), out)
    for kind, pat in _FREE:
        for m in list(re.finditer(pat, out)):
            val = m.group(0)
            if val.startswith("["):
                continue
            out = out.replace(val, ph_for(kind, val))
    return ScrubResult(out, mapping)
