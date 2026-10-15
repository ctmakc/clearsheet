#!/usr/bin/env python3
"""Record the demo: drive the real app with Playwright, log when each scene starts.

python3 docs/video/record.py http://127.0.0.1:8090   -> docs/video/out/raw.webm + marks.json
The app must be running (live mode for the real AMD run).
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "out"
URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8090"
CASE, LANG = "01_heart_failure", "uk"

marks: list[tuple[str, float]] = []
t0 = 0.0


def mark(name: str) -> None:
    marks.append((name, round(time.time() - t0, 2)))
    print(name, marks[-1][1], flush=True)


def main() -> None:
    global t0
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1600, "height": 900}, record_video_dir=str(OUT),
                            record_video_size={"width": 1600, "height": 900}, device_scale_factor=1)
        pg = ctx.new_page()
        t0 = time.time()
        pg.goto(URL, wait_until="networkidle")
        pg.wait_for_timeout(1500)
        mark("problem")
        pg.mouse.wheel(0, 260); pg.wait_for_timeout(2500); pg.mouse.wheel(0, -260)
        pg.wait_for_timeout(2500)
        mark("run")
        pg.select_option("#lang", LANG); pg.wait_for_timeout(700)
        pg.fill("#reviewer", "RN-KT"); pg.wait_for_timeout(500)
        pg.click("#run")
        mark("wait")
        pg.wait_for_selector(".row", timeout=900_000)
        mark("results")
        pg.wait_for_timeout(4000)
        mark("trace")
        pg.click('.row[data-id="M1"]'); pg.wait_for_timeout(5000)
        mark("risk")
        pg.click('.row[data-id="M5"]'); pg.wait_for_timeout(5500)
        mark("catch")
        target = "W3"
        pg.click(f'.row[data-id="{target}"]'); pg.wait_for_timeout(7000)
        mark("fix")
        flagged = pg.eval_on_selector_all(".row", "rs => rs.filter(r => r.querySelector('.chip.review') && r.querySelector('.details').textContent.includes('adds numbers')).map(r => r.dataset.id)")
        for rid in flagged:
            row = f'.row[data-id="{rid}"]'
            if "sel" not in (pg.get_attribute(row, "class") or ""):
                pg.click(row)
            pg.click(f'{row} [data-edit]')
            ta = f"{row} textarea"
            pg.fill(ta, pg.input_value(ta).replace("103", "911"))
            pg.click(f"{row} .details button.edit")
            pg.wait_for_timeout(400)
        mark("release")
        others = pg.eval_on_selector_all("[data-rel]", "cs => cs.filter(c => !c.checked && !c.disabled).map(c => c.dataset.rel)")
        for rid in others:
            pg.check(f'[data-rel="{rid}"]'); pg.wait_for_timeout(250)
        pg.wait_for_timeout(1200)
        pg.click("#release")
        pg.wait_for_selector("#overlay:not([hidden])")
        mark("sheet")
        pg.wait_for_timeout(3000)
        frame = pg.frame_locator("#sheetFrame")
        for _ in range(6):
            frame.locator("body").evaluate("() => window.scrollBy(0, 260)"); pg.wait_for_timeout(900)
        pg.wait_for_timeout(1500)
        pg.click("#close")
        mark("numbers")
        pg.evaluate("document.getElementById('evalbox').scrollIntoView({block:'start', behavior:'smooth'})")
        pg.wait_for_timeout(9000)
        pg.evaluate("document.getElementById('log').scrollIntoView({block:'start', behavior:'smooth'})")
        pg.wait_for_timeout(6000)
        mark("end")
        video = pg.video.path()
        ctx.close(); b.close()
    pathlib.Path(video).rename(OUT / "raw.webm")
    (OUT / "marks.json").write_text(json.dumps(marks, indent=1))


if __name__ == "__main__":
    main()
