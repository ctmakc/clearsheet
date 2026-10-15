#!/usr/bin/env python3
"""Build docs/clearsheet-deck.pdf (16:9) and docs/cover.png from real run artefacts.

Numbers come from eval/results.json and eval/bench.json; screenshots from docs/shots/.
python3 docs/build_deck.py
"""
from __future__ import annotations

import base64
import json
import pathlib

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
R = json.loads((ROOT / "eval" / "results.json").read_text())
B = json.loads((ROOT / "eval" / "bench.json").read_text()) if (ROOT / "eval" / "bench.json").exists() else None


def img(name: str) -> str:
    p = DOCS / "shots" / name
    return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()


def pct(x) -> str:
    return "n/a" if x is None else f"{round(x * 100)}%"


M = R["medications"]
MT = R["mutation_test"]
TM = R["translation_mutation_test"]
best = max(B["rows"], key=lambda r: r["output_tok_per_s"]) if B else None
one = min(B["rows"], key=lambda r: r["concurrency"]) if B else None
# cost per patient sheet at the measured batched rate (formula shown on the slide)
tok_per_case = (R["prompt_tokens"] + R["completion_tokens"]) / max(1, R["docs"] * len(R["languages"]))
out_per_case = R["completion_tokens"] / max(1, R["docs"] * len(R["languages"]))
sec_per_case = (out_per_case / best["output_tok_per_s"]) if best else None
usd_per_case = (sec_per_case / 3600 * 1.99) if sec_per_case else None

CSS = """
@page{size:1920px 1080px;margin:0}
*{box-sizing:border-box}
html,body{margin:0}
body{font-family:'Noto Sans',sans-serif;color:#18222F;background:#F6F7F4}
.s{width:1920px;height:1080px;position:relative;overflow:hidden;page-break-after:always;padding:96px 120px;background:#F6F7F4}
h1,h2{font-family:Lexend,sans-serif;margin:0;letter-spacing:-.015em}
h1{font-size:120px;font-weight:600;line-height:1}
h2{font-size:64px;font-weight:600;line-height:1.08;max-width:1500px}
.k{font:500 24px Lexend,sans-serif;text-transform:uppercase;letter-spacing:.08em;color:#4A5563;margin-bottom:28px}
p,li{font-size:34px;line-height:1.42;max-width:1400px}
.hl{background:linear-gradient(#EDF25C,#EDF25C) 0 90%/100% 55% no-repeat}
.mono{font-family:'JetBrains Mono',monospace}
.rule{border-top:3px solid #18222F;margin:40px 0 0}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:0;border-top:3px solid #18222F;margin-top:56px}
.grid div{padding:34px 30px 34px 0;border-bottom:1px solid #D5D9D3}
.grid b{display:block;font:600 92px/1 Lexend,sans-serif;letter-spacing:-.02em}
.grid span{font-size:26px;color:#4A5563;display:block;margin-top:10px;max-width:480px}
.shot{position:absolute;right:80px;top:120px;width:1180px;height:840px;object-fit:cover;object-position:top left;border-radius:6px;box-shadow:0 30px 80px -30px rgba(24,34,47,.45);border:1px solid #D5D9D3;background:#fff}
.pipe{display:grid;grid-template-columns:repeat(7,1fr);gap:14px;margin-top:64px}
.pipe div{border-top:6px solid #18222F;padding-top:18px;font-size:25px;line-height:1.35}
.pipe div.m{border-color:#1D3F8F}.pipe div.c{border-color:#2E7D4F}.pipe div.n{border-color:#A86312}
.pipe b{display:block;font:600 28px Lexend,sans-serif;margin-bottom:8px}
.tag{display:inline-block;font:600 20px Lexend,sans-serif;text-transform:uppercase;letter-spacing:.06em;padding:6px 12px;border:2px solid currentColor;border-radius:4px}
.ok{color:#2E7D4F}.rv{color:#A86312}.bl{color:#B42318}
.foot{position:absolute;left:120px;bottom:56px;font:500 22px Lexend,sans-serif;color:#4A5563}
.ex{font:30px/1.5 'JetBrains Mono',monospace;background:#fff;border:1px solid #D5D9D3;padding:28px 34px;margin-top:40px;max-width:1500px}
table{border-collapse:collapse;margin-top:44px;font-size:30px}
td,th{padding:14px 30px 14px 0;border-bottom:1px solid #D5D9D3;text-align:left}
th{font:500 22px Lexend,sans-serif;text-transform:uppercase;letter-spacing:.06em;color:#4A5563}
td.n{font-family:'JetBrains Mono',monospace;text-align:right}
"""

FONTS = ('<link href="https://fonts.googleapis.com/css2?family=Lexend:wght@500;600&family=Noto+Sans:wght@400;600'
         '&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">')


def slides() -> list[str]:
    s = []
    s.append(f"""<section class="s"><div class="k">AMD Developer Hackathon ACT III · Health and Wellbeing</div>
<h1>Clearsheet</h1><p style="font-size:44px;margin-top:36px;max-width:1300px">Discharge instructions a patient can follow, in their own language.
<span class="hl">Every line traced to the source</span> and released by a nurse.</p>
<p style="color:#4A5563;margin-top:60px">Gemma 3 27B on one AMD Instinct MI300X · vLLM on ROCm · team Innova Ottawa</p></section>""")
    s.append("""<section class="s"><div class="k">The problem</div>
<h2>The discharge summary is written for clinicians. The patient takes it home.</h2>
<div class="ex">Furosemide 40 mg PO BID (INCREASED from 20 mg daily).<br>Metoprolol succinate 50 mg PO daily. Hold if heart rate below 55.<br>Potassium chloride 20 mEq PO daily - STOPPED. Do not take.</div>
<p style="margin-top:44px">Many patients read English as a second language. A language model rewrites and translates this in seconds,
and it can also change a dose, drop a "stop", or swap a phone number. Nobody at the bedside can proofread a sheet in Ukrainian or Arabic.</p></section>""")
    s.append("""<section class="s"><div class="k">How it works</div><h2>The model drafts. Code decides what may reach the patient. The nurse decides the rest.</h2>
<div class="pipe">
<div class="c"><b>1 Scrub</b>names, MRN, health card, DOB, phone masked on the hospital side, before any model call</div>
<div class="m"><b>2 Extract</b>Gemma lists medicines, follow-ups, warning signs, each with a verbatim source quote</div>
<div class="c"><b>3 Ground</b>quote must exist in the document; every number must sit inside its quote</div>
<div class="c"><b>4 Risk</b>anticoagulants, insulin, opioids, stops and dose changes always go to a nurse</div>
<div class="m"><b>5 Explain</b>plain English plus the patient's language</div>
<div class="m"><b>6 Back-check</b>literal back-translation; numbers and drug names compared in code</div>
<div class="n"><b>7 Release</b>nurse releases flagged lines; blocked lines stay off the sheet</div>
</div><p style="margin-top:56px"><span class="tag ok">verified</span>&nbsp; <span class="tag rv">nurse check</span>&nbsp; <span class="tag bl">blocked</span></p></section>""")
    s.append(f"""<section class="s"><div class="k">Nurse review console</div><h2 style="max-width:500px">Click a line, see where it came from.</h2>
<p style="max-width:500px;font-size:30px;margin-top:30px">The highlighter marks the source sentence. The nurse sees the back-translation of what the patient will read.</p>
<img class="shot" src="{img('console.png')}"></section>""")
    s.append("""<section class="s"><div class="k">Real catches from our runs on the MI300X</div><h2>Gemma translated "call 911" into Ukrainian as "call 103".</h2>
<div class="ex">EN  If you have chest pain, go to the Emergency Department or call 911.<br>UK  … зверніться до відділення невідкладної допомоги або зателефонуйте 103.</div>
<p style="margin-top:36px">103 is the ambulance number in Ukraine. The patient is in Canada. The check flags any number that is not in the source, so the line went to the nurse.
We then added a prompt rule ("911 stays 911"); the check stays as the safety net.</p>
<div class="ex" style="margin-top:28px">SOURCE  Seek emergency care if: black or bloody stools …<br>DRAFT   Tell your doctor if you have black or bloody stools.<br>→ passed our first checks; the urgency check we added now flags it</div></section>""")
    s.append(f"""<section class="s"><div class="k">Patient sheet</div><h2 style="max-width:500px">Their language first, English underneath, medicines as a pill-box grid.</h2>
<img class="shot" src="{img('sheet.png')}"></section>""")
    bench = ""
    if B:
        rows = "".join(f"<tr><td>{r['concurrency']}</td><td class='n'>{r['output_tok_per_s']}</td><td class='n'>{r['docs_per_min']}</td><td class='n'>{r['p50_latency_s']}</td></tr>" for r in B["rows"])
        bench = f"<table><tr><th>Parallel requests</th><th>Output tok/s</th><th>Summaries/min (extract)</th><th>p50 latency s</th></tr>{rows}</table>"
    s.append(f"""<section class="s"><div class="k">Measured on 8 synthetic discharge summaries × {len(R['languages'])} languages</div>
<h2>What the checks did</h2>
<div class="grid">
<div><b>{pct(M['recall'])}</b><span>medicines found ({M['tp']} of {M['gt']})</span></div>
<div><b>{pct(M['dose_exact'])}</b><span>of found medicines with the exact dose</span></div>
<div><b>{pct(M['status_accuracy'])}</b><span>new / changed / stopped labelled right</span></div>
<div><b>{pct(MT['rate'])}</b><span>injected wrong numbers and invented quotes blocked ({MT['caught']} of {MT['total']})</span></div>
<div><b>{pct(TM['rate'])}</b><span>wrong doses planted in translations flagged ({TM['caught']} of {TM['total']})</span></div>
<div><b>{pct(R['urgency_mutation_test']['rate'])}</b><span>emergency lines softened to "tell your doctor" flagged ({R['urgency_mutation_test']['caught']} of {R['urgency_mutation_test']['total']})</span></div>
</div><div class="foot">eval/results.json · {R['calls']} model calls · {R['prompt_tokens'] + R['completion_tokens']:,} tokens · {R['run_at']} · {R['model']} · {R['backend']}</div></section>""")
    cost = (f"<p style='margin-top:40px'>At the batched rate, one patient sheet (extract + explain + back-check, about {round(out_per_case)} output tokens) "
            f"takes about {sec_per_case:.1f} GPU-seconds: ${usd_per_case:.4f} at $1.99 per MI300X-hour (AMD Developer Cloud list price, 2025).</p>") if usd_per_case else ""
    s.append(f"""<section class="s"><div class="k">AMD Instinct MI300X</div><h2>192 GB on one GPU: a 27B model in bf16 with room to batch a ward's discharges.</h2>
{bench}{cost}<div class="foot">eval/bench.json · vLLM V1 engine on ROCm · gemma-3-27b-it bf16</div></section>""")
    s.append("""<section class="s"><div class="k">Who pays and what is next</div><h2>Hospitals and home-care agencies, per discharge, inside the nurse's existing workflow.</h2>
<ul style="margin-top:40px"><li>Runs on the hospital's own AMD GPU or a private endpoint: masked text only, no patient identifiers leave the building.</li>
<li>It does not diagnose, change doses or add advice. The sheet says so.</li>
<li>Next: pilot with a newcomer-serving clinic in Ottawa, pharmacist review of the high-alert list, more languages with native-speaker QA.</li></ul>
<p style="margin-top:50px" class="mono">github.com/ctmakc/clearsheet · MIT</p></section>""")
    return s


def main() -> None:
    html = f"<!doctype html><html><head><meta charset='utf-8'>{FONTS}<style>{CSS}</style></head><body>{''.join(slides())}</body></html>"
    (DOCS / "deck.html").write_text(html, encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1920, "height": 1080})
        pg.goto((DOCS / "deck.html").as_uri(), wait_until="networkidle")
        pg.wait_for_timeout(800)
        pg.pdf(path=str(DOCS / "clearsheet-deck.pdf"), width="1920px", height="1080px", print_background=True)
        for i in range(len(slides())):
            pg.evaluate(f"window.scrollTo(0,{i * 1080})")
            pg.screenshot(path=str(DOCS / "shots" / f"slide{i + 1:02d}.png"), clip={"x": 0, "y": i * 1080, "width": 1920, "height": 1080}, full_page=True)
        b.close()
    cover = f"""<!doctype html><html><head><meta charset='utf-8'>{FONTS}<style>{CSS}
.cv{{width:1920px;height:1080px;position:relative;overflow:hidden;background:#F6F7F4;padding:110px 120px}}
.cv .shot{{top:150px;right:-60px;width:1120px;height:780px}}
</style></head><body><div class="cv"><div class="k">AMD Developer Hackathon ACT III · Health and Wellbeing</div>
<h1 style="font-size:132px">Clearsheet</h1>
<p style="font-size:44px;max-width:700px;margin-top:40px">Discharge instructions a patient can follow, in their language. <span class="hl">Every line traced to the source,</span> released by a nurse.</p>
<p style="font-size:28px;color:#4A5563;max-width:700px;margin-top:50px">Gemma 3 27B · AMD Instinct MI300X · vLLM on ROCm</p>
<img class="shot" src="{img('console.png')}"></div></body></html>"""
    (DOCS / "cover.html").write_text(cover, encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1920, "height": 1080})
        pg.goto((DOCS / "cover.html").as_uri(), wait_until="networkidle"); pg.wait_for_timeout(600)
        pg.screenshot(path=str(DOCS / "cover.png")); b.close()
    (DOCS / "cover.html").unlink()
    print("ok", DOCS / "clearsheet-deck.pdf")


if __name__ == "__main__":
    main()
