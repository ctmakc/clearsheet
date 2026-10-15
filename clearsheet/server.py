"""Clearsheet web app: nurse review console + printable patient sheet.

uvicorn clearsheet.server:app --port 8090
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import pipeline
from .llm import LLM, ReplayMiss
from .sheet import render_sheet

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
SAMPLES = ROOT / "samples"

app = FastAPI(title="Clearsheet")
app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")

_RUNS: dict[str, pipeline.Result] = {}


def _llm() -> LLM:
    return LLM.from_env()


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/status")
def status():
    llm = _llm()
    rec = ROOT / "recordings" / "calls.jsonl"
    recorded = []
    if rec.exists():
        for line in rec.read_text(encoding="utf-8").splitlines()[:1]:
            r = json.loads(line)
            recorded = [r.get("backend"), r.get("model"), r.get("recorded_at")]
    return {"mode": llm.mode, "model": llm.model, "backend": llm.backend_label,
            "recorded": recorded, "languages": pipeline.LANGUAGES}


@app.get("/api/samples")
def samples():
    out = []
    for p in sorted(SAMPLES.glob("*.txt")):
        lines = p.read_text(encoding="utf-8").splitlines()
        title = next((l.split(":", 1)[1].strip() for l in lines if l.lower().startswith(("diagnosis", "diagnoses", "reason for admission", "procedure", "surgery"))), p.stem)
        title = title.split(". ")[0].split(" (")[0].rstrip(".")
        out.append({"id": p.stem, "title": title[:60]})
    return out


@app.get("/api/sample/{doc_id}")
def sample(doc_id: str):
    p = SAMPLES / f"{doc_id}.txt"
    if not p.exists() or "/" in doc_id:
        raise HTTPException(404)
    return {"id": doc_id, "text": p.read_text(encoding="utf-8")}


class RunReq(BaseModel):
    text: str
    lang: str = "uk"
    doc_id: str = "pasted"


def _item_json(it: pipeline.Item) -> dict:
    return {"id": it.id, "kind": it.kind, "data": it.data, "state": it.state,
            "grounding": it.check["grounding"], "issues": it.check["issues"], "risk": it.check["risk"],
            "translation_issues": it.translation_issues, "plain_en": it.plain_en,
            "patient": it.patient, "back_en": it.back_en, "schedule": it.schedule}


@app.post("/api/run")
def run(req: RunReq):
    if req.lang not in pipeline.LANGUAGES:
        raise HTTPException(400, "unknown language")
    if len(req.text) > 12000:
        raise HTTPException(400, "document too long for the demo (12k characters max)")
    llm = _llm()
    t0 = time.time()
    try:
        res = pipeline.run(llm, req.doc_id, req.text, req.lang)
    except ReplayMiss:
        return JSONResponse(status_code=409, content={
            "error": "replay_miss",
            "message": "The live AMD GPU endpoint is offline, and this exact document/language was not "
                       "recorded. Pick one of the sample cases with a recorded language, or run with "
                       "CLEARSHEET_BASE_URL set to a vLLM/Token Factory endpoint."})
    run_id = f"{int(t0 * 1000)}"
    _RUNS[run_id] = res
    while len(_RUNS) > 50:
        _RUNS.pop(next(iter(_RUNS)))
    return {
        "run_id": run_id, "doc_id": req.doc_id, "lang": req.lang,
        "lang_name": pipeline.LANGUAGES[req.lang],
        "scrubbed": res.scrubbed.text, "masked": res.scrubbed.counts,
        "items": [_item_json(i) for i in res.items], "states": res.by_state(),
        "stats": [s.__dict__ for s in llm.stats], "seconds": round(time.time() - t0, 2),
        "mode": llm.mode, "backend": llm.backend_label, "model": llm.model,
    }


class SheetReq(BaseModel):
    run_id: str
    approved: list[str]
    edits: dict[str, str] = {}
    reviewer: str = ""


@app.post("/api/sheet", response_class=HTMLResponse)
def sheet(req: SheetReq):
    res = _RUNS.get(req.run_id)
    if res is None:
        raise HTTPException(404, "run expired; run the case again")
    blocked = [i.id for i in res.items if i.state == "blocked" and i.id in req.approved and i.id not in req.edits]
    if blocked:
        raise HTTPException(400, f"blocked items cannot be released without an edit: {blocked}")
    return render_sheet(res, set(req.approved), req.edits, req.reviewer)


@app.get("/api/eval")
def eval_results():
    p = ROOT / "eval" / "results.json"
    if not p.exists():
        raise HTTPException(404)
    return json.loads(p.read_text())
