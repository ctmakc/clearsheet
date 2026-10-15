"""Printable patient sheet. Only items a nurse released reach this page."""
from __future__ import annotations

import html
import time

from .pipeline import LANGUAGES, Result

L = {
    "en": dict(title="Going home: your instructions", meds="Your medicines", stop="Stop taking these",
               appts="Appointments and tests", care="Looking after yourself",
               er="Get help now", slots=["Morning", "Midday", "Evening", "Bedtime", "Only when needed"],
               med="Medicine"),
    "fr": dict(title="Retour à la maison : vos consignes", meds="Vos médicaments", stop="Arrêtez de prendre",
               appts="Rendez-vous et examens", care="Prendre soin de vous",
               er="Obtenez de l'aide maintenant", slots=["Matin", "Midi", "Soir", "Coucher", "Seulement au besoin"],
               med="Médicament"),
    "uk": dict(title="Виписка додому: ваші інструкції", meds="Ваші ліки", stop="Припиніть приймати",
               appts="Прийоми та аналізи", care="Догляд за собою",
               er="Негайно зверніться по допомогу",
               slots=["Ранок", "Обід", "Вечір", "Перед сном", "Лише за потреби"], med="Ліки"),
    "es": dict(title="De vuelta a casa: sus instrucciones", meds="Sus medicamentos", stop="Deje de tomar",
               appts="Citas y pruebas", care="Cómo cuidarse",
               er="Busque ayuda ahora", slots=["Mañana", "Mediodía", "Tarde", "Al acostarse", "Solo si lo necesita"],
               med="Medicamento"),
    "zh": dict(title="出院回家：您的注意事项", meds="您的药物", stop="请停止服用", appts="复诊和检查",
               care="自我护理", er="立即求助", slots=["早上", "中午", "晚上", "睡前", "仅在需要时"],
               med="药物"),
    "ar": dict(title="العودة إلى المنزل: تعليماتك", meds="أدويتك", stop="توقف عن تناول", appts="المواعيد والفحوصات",
               care="العناية بنفسك", er="اطلب المساعدة فورًا",
               slots=["الصباح", "الظهر", "المساء", "قبل النوم", "عند الحاجة فقط"], med="الدواء"),
}
SLOT_KEYS = ["morning", "midday", "evening", "bedtime"]


def _e(s: str) -> str:
    return html.escape(s or "")


def render_sheet(res: Result, approved: set[str], edits: dict[str, str], reviewer: str) -> str:
    lang = res.lang
    t = L.get(lang, L["en"])
    en = L["en"]
    rtl = lang == "ar"
    restore = res.scrubbed.restore
    name = res.scrubbed.mapping.get("[NAME_1]", "")

    def txt(it) -> tuple[str, str]:
        p = edits.get(it.id, it.patient)
        return restore(p), restore(it.plain_en)

    items = [i for i in res.items if i.id in approved]
    meds = [i for i in items if i.kind == "medication" and not (i.schedule or {}).get("stopped")]
    stopped = [i for i in items if i.kind == "medication" and (i.schedule or {}).get("stopped")]
    appts = [i for i in items if i.kind == "follow_up"]
    care = [i for i in items if i.kind == "self_care"]
    warns = [i for i in items if i.kind == "warning"]
    emerg = [i for i in items if i.kind == "emergency"]

    def bi(it, cls=""):
        p, e = txt(it)
        second = "" if lang == "en" else f'<div class="en">{_e(e)}</div>'
        return f'<div class="pt {cls}">{_e(p)}</div>{second}'

    rows = []
    for m in meds:
        sch = m.schedule or {"slots": [], "prn": False}
        cells = "".join(f'<td class="slot">{"<span class=dot></span>" if k in sch["slots"] else ""}</td>' for k in SLOT_KEYS)
        cells += f'<td class="slot">{"<span class=dot prn></span>" if sch.get("prn") else ""}</td>'
        if m.schedule is None:
            cells = f'<td class="slot see" colspan="5">{_e(t["meds"])} →</td>'
        rows.append(f'<tr><th class="drug"><b>{_e(m.data.get("name"))}</b><small>{_e(m.data.get("dose"))}</small></th>'
                    f'{cells}<td class="how">{bi(m)}</td></tr>')

    def heads():
        return "".join(f'<th class="slot"><span>{_e(a)}</span>{"" if lang == "en" else f"<small>{_e(b)}</small>"}</th>'
                       for a, b in zip(t["slots"], en["slots"]))

    def section(title_key, its, cls=""):
        if not its:
            return ""
        lis = "".join(f"<li>{bi(i)}</li>" for i in its)
        sub = "" if lang == "en" else f'<small>{_e(en[title_key])}</small>'
        return f'<section class="{cls}"><h2>{_e(t[title_key])}{sub}</h2><ul>{lis}</ul></section>'

    er_lis = "".join(f"<li>{bi(i)}</li>" for i in warns)
    if emerg:
        er_head = bi(emerg[0])
    else:
        # no separate action line was extracted: print the document's own lead-in, verbatim, in English
        lead = ""
        for w in warns:
            q = w.data.get("source_quote", "")
            i = res.scrubbed.text.find(q) if q else -1
            if i >= 0:
                line = res.scrubbed.text[:i].rsplit("\n", 1)[-1] + q
                if ":" in line:
                    lead = line.split(":")[0].strip()
                    break
        er_head = f'<div class="pt src">{_e(restore(lead))}:</div><div class="en">from the discharge summary, as written</div>' if lead else ""
    er_sub = "" if lang == "en" else f'<small>{_e(en["er"])}</small>'
    er = (f'<section class="er"><h2>{_e(t["er"])}{er_sub}</h2>{er_head}<ul>{er_lis}</ul></section>'
          if warns or emerg else "")
    stamp = time.strftime("%Y-%m-%d %H:%M")
    meds_sub = "" if lang == "en" else f"<small>{_e(en['meds'])}</small>"
    med_table = (f'<section><h2>{_e(t["meds"])}{meds_sub}</h2>'
                 f'<table class="grid"><thead><tr><th class="drug">{_e(t["med"])}</th>{heads()}<th></th></tr></thead>'
                 f'<tbody>{"".join(rows)}</tbody></table></section>') if meds else ""

    return f"""<!doctype html><html lang="{lang}" dir="{'rtl' if rtl else 'ltr'}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{_e(t['title'])}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Lexend:wght@500;600&family=Noto+Sans:wght@400;600&family=Noto+Sans+SC:wght@400;600&family=Noto+Sans+Arabic:wght@400;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/sheet.css"></head><body class="lang-{lang}">
<main class="sheet">
<header><div><h1>{_e(t['title'])}</h1>{"" if lang == "en" else f'<p class="en">{_e(en["title"])}</p>'}</div>
<dl><dt>Patient</dt><dd>{_e(name)}</dd><dt>Language</dt><dd>{_e(LANGUAGES[lang])}</dd><dt>Printed</dt><dd>{stamp}</dd></dl></header>
{er}
{med_table}
{section('stop', stopped, 'stop')}
{section('appts', appts)}
{section('care', care)}
<footer>Reviewed and released by {_e(reviewer) or '________'} · every line on this sheet is traced to the hospital discharge summary and was checked by a nurse before printing. This sheet does not replace advice from your care team.</footer>
</main></body></html>"""
