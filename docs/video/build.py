#!/usr/bin/env python3
"""Cut the recorded screen session into narrated scenes and render the MP4.

python3 docs/video/build.py   (after record.py)  -> docs/video/out/clearsheet-demo.mp4 (+ .srt)
Narration numbers are read from eval/results.json and eval/bench.json.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "out"
R = json.loads((ROOT / "eval" / "results.json").read_text())
B = json.loads((ROOT / "eval" / "bench.json").read_text())
EDGE = os.environ.get("EDGE_TTS", "/data/venvs/edge-tts/bin/edge-tts")
VOICE, RATE = "en-US-AndrewNeural", "+4%"


def pct(x):
    return f"{round(x * 100)} percent"


best = max(B["rows"], key=lambda r: r["output_tok_per_s"])
NARR = {
    "intro": "Clearsheet turns a hospital discharge summary into instructions a patient can follow, in their own language. "
             "Gemma 3 drafts every line on an AMD Instinct MI300X. Code and a nurse decide what reaches the patient.",
    "problem": "This summary is written for clinicians: P O, B I D, hold if heart rate below fifty-five. "
               "Many patients read English as a second language, and a model that translates it can quietly change a dose or a phone number.",
    "run": "We pick the patient's language, Ukrainian, and run the case live. Names, record numbers and phone numbers are masked on this machine first.",
    "wait": "Gemma 3, 27 billion parameters in b-float-16, runs on one MI300X with v-L-L-M on rock-m. It extracts the facts, writes the plain version, the translation, and a back-translation. This wait is sped up.",
    "results": "Every line comes back with a state: verified, nurse check, or blocked.",
    "trace": "Each line carries the sentence it came from. Click it, and the highlighter shows the source. Every number has to appear inside that quote, or the line is blocked.",
    "risk": "Stopped medicines, dose changes, and high-alert drugs like blood thinners, insulin and opioids always go to the nurse.",
    "catch": "Here is a real catch from this run. Gemma translated call nine-one-one as call one-zero-three, the ambulance number in Ukraine. "
             "The patient lives in Canada. Any number the source does not contain gets flagged, and the nurse reads the back-translation in English.",
    "fix": "The nurse corrects those lines herself.",
    "release": "She releases the remaining checked lines. Nothing prints until every flagged line has a decision.",
    "sheet": "The patient sheet: Ukrainian first, English underneath, emergency signs at the top, medicines as a pill-box grid, and the stopped medicine crossed out.",
    "numbers": f"On eight synthetic cases in six languages, Clearsheet found {pct(R['medications']['recall'])} of the medicines with {pct(R['medications']['dose_exact'])} exact doses. "
               f"When we planted wrong numbers and invented sentences, the checks blocked {pct(R['mutation_test']['rate'])} of them. "
               f"In our batch benchmark, one MI300X served {round(best['output_tok_per_s'])} output tokens per second across 64 parallel requests.",
    "end": "Clearsheet is open source under M I T. It does not diagnose or change treatment. It makes what the care team wrote readable, and checkable.",
}
ORDER = ["problem", "run", "wait", "results", "trace", "risk", "catch", "fix", "release", "sheet", "numbers"]


def sh(*a):
    subprocess.run(a, check=True)


def dur(p) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True, check=True).stdout.strip())


def tts(key: str) -> pathlib.Path:
    mp3 = OUT / f"vo_{key}.mp3"
    if mp3.exists() and mp3.stat().st_size:
        return mp3
    for i in range(3):
        r = subprocess.run([EDGE, "--voice", VOICE, f"--rate={RATE}", "--text", NARR[key], "--write-media", str(mp3)],
                           capture_output=True, text=True)
        if r.returncode == 0 and mp3.exists() and mp3.stat().st_size:
            return mp3
        time.sleep(2 + i)
    raw = mp3.with_suffix(".g.mp3")
    sh("gtts-cli", NARR[key], "-l", "en", "-o", str(raw))
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-af", "atempo=1.12", str(mp3))
    return mp3


def title_card(key: str, seconds: float) -> pathlib.Path:
    png = OUT / f"card_{key}.png"
    from playwright.sync_api import sync_playwright
    txt = {"intro": ("Clearsheet", "Discharge instructions a patient can follow. Every line traced to the source, released by a nurse.",
                     "Gemma 3 27B · AMD Instinct MI300X · vLLM on ROCm"),
           "end": ("github.com/ctmakc/clearsheet", "MIT · synthetic data only · AMD Developer Hackathon ACT III", "Team Innova Ottawa")}[key]
    html = f"""<html><head><link href="https://fonts.googleapis.com/css2?family=Lexend:wght@500;600&family=Noto+Sans&display=swap" rel="stylesheet">
<style>body{{margin:0;width:1600px;height:900px;background:#F6F7F4;color:#18222F;font-family:'Noto Sans';display:flex;flex-direction:column;justify-content:center;padding:0 120px;box-sizing:border-box}}
h1{{font:600 96px Lexend;margin:0 0 30px;letter-spacing:-.02em}}p{{font-size:34px;max-width:1150px;margin:0 0 24px;line-height:1.4}}
.m{{width:60px;height:60px;border:3px solid #18222F;border-radius:6px;margin-bottom:36px;background:linear-gradient(#EDF25C,#EDF25C) 0 60%/100% 34% no-repeat}}
small{{font:500 26px Lexend;color:#4A5563}}</style></head><body><div class="m"></div><h1>{txt[0]}</h1><p>{txt[1]}</p><small>{txt[2]}</small></body></html>"""
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1600, "height": 900})
        pg.set_content(html, wait_until="networkidle"); pg.wait_for_timeout(500); pg.screenshot(path=str(png)); b.close()
    mp4 = OUT / f"seg_{key}.mp4"
    sh("ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(png), "-t", f"{seconds:.2f}", "-r", "30",
       "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "20", str(mp4))
    return mp4


def srt_time(t: float) -> str:
    h, m = int(t // 3600), int(t % 3600 // 60)
    s = t % 60
    return f"{h:02d}:{m:02d}:{int(s):02d},{int(round((s - int(s)) * 1000)):03d}"


def main() -> None:
    marks = dict(json.loads((OUT / "marks.json").read_text()))
    keys = list(marks)
    raw = OUT / "raw.webm"
    total_raw = dur(raw)
    segs, srt, clock = [], [], 0.0
    PAD = 0.6

    def add(key, video, vo):
        nonlocal clock
        d = dur(video)
        srt.append((clock, clock + dur(vo), NARR[key]))
        segs.append((video, vo, d))
        clock += d

    vo = tts("intro"); add("intro", title_card("intro", dur(vo) + PAD), vo)
    for i, key in enumerate(ORDER):
        start = marks[key]
        nxt = next((marks[k] for k in keys[keys.index(key) + 1:]), total_raw)
        length = max(0.5, nxt - start)
        vo = tts(key)
        need = dur(vo) + PAD
        speed = max(1.0, length / need) if key == "wait" else 1.0
        out_len = length / speed
        mp4 = OUT / f"seg_{key}.mp4"
        vf = (f"setpts=PTS/{speed:.4f}" if speed > 1 else "setpts=PTS") + ",fps=30"
        if out_len < need:
            vf += f",tpad=stop_mode=clone:stop_duration={need - out_len + 0.05:.2f}"
        vf += ",format=yuv420p"
        sh("ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", str(raw),
           "-vf", vf, "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-t", f"{max(need, out_len):.2f}", str(mp4))
        add(key, mp4, vo)
    vo = tts("end"); add("end", title_card("end", dur(vo) + PAD + 0.8), vo)

    # audio track: each voice-over placed at its scene start
    inputs, filters = [], []
    t = 0.0
    for i, (video, vo, d) in enumerate(segs):
        inputs += ["-i", str(vo)]
        filters.append(f"[{i}:a]adelay={int(t * 1000)}|{int(t * 1000)}[a{i}]")
        t += d
    mix = "".join(f"[a{i}]" for i in range(len(segs)))
    audio = OUT / "voice.m4a"
    sh("ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex",
       ";".join(filters) + f";{mix}amix=inputs={len(segs)}:normalize=0,volume=1.0[out]", "-map", "[out]",
       "-c:a", "aac", "-b:a", "160k", "-t", f"{t:.2f}", str(audio))
    lst = OUT / "concat.txt"
    lst.write_text("".join(f"file '{v}'\n" for v, _, _ in segs))
    video = OUT / "video.mp4"
    sh("ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(video))
    srt_path = OUT / "clearsheet-demo.srt"
    srt_path.write_text("".join(f"{i + 1}\n{srt_time(a)} --> {srt_time(b)}\n{txt}\n\n" for i, (a, b, txt) in enumerate(srt)))
    final = OUT / "clearsheet-demo.mp4"
    style = "FontName=Noto Sans,FontSize=15,PrimaryColour=&H00F4F7F6,BackColour=&H102F2218,BorderStyle=4,Outline=0,Shadow=0,MarginV=22"
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio),
       "-vf", f"subtitles={srt_path}:force_style='{style}'", "-c:v", "libx264", "-preset", "medium", "-crf", "21",
       "-c:a", "copy", "-movflags", "+faststart", str(final))
    print("ok", final, round(dur(final), 1), "s")


if __name__ == "__main__":
    main()
