"""Evaluate Clearsheet on the synthetic discharge set.

python -m eval.run_eval --langs uk fr es zh   (live endpoint from env, or replay)

Writes eval/results.json and eval/REPORT.md. Every number in the report
comes from this run; nothing is typed in by hand.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from clearsheet import pipeline, verify
from clearsheet.llm import LLM
from clearsheet.scrub import scrub

ROOT = Path(__file__).resolve().parent.parent
GT = json.loads((ROOT / "eval" / "ground_truth.json").read_text())


def load_docs() -> dict[str, str]:
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted((ROOT / "samples").glob("*.txt"))}


def _key(name: str) -> str:
    return verify.norm(name).replace("-", " ").split(" ")[0]


def score_meds(doc_id: str, items: list[pipeline.Item]) -> dict:
    gt = GT[doc_id]["medications"]
    meds = [it for it in items if it.kind == "medication"]
    matched_gt, matched_ex = set(), set()
    dose_ok = status_ok = status_n = 0
    for gi, g in enumerate(gt):
        for ei, it in enumerate(meds):
            if ei in matched_ex:
                continue
            if _key(g["name"]) == _key(it.data.get("name", "")) or _key(g["name"]) in verify.norm(it.data.get("name", "")):
                matched_gt.add(gi); matched_ex.add(ei)
                if set(verify.numbers(g["dose"])) <= set(verify.numbers(it.data.get("dose", ""))):
                    dose_ok += 1
                if g["status"] != "unspecified":
                    status_n += 1
                    st = it.data.get("status")
                    if st == g["status"] or (g["status"] == "changed" and st == "hold"):
                        status_ok += 1
                break
    return {"gt": len(gt), "extracted": len(meds), "tp": len(matched_gt), "dose_ok": dose_ok,
            "status_ok": status_ok, "status_n": status_n}


def mutation_test(doc: str, items: list[pipeline.Item]) -> dict:
    """Simulate the two failure modes that hurt patients: a wrong number and
    an invented instruction. Count how many the deterministic checks catch."""
    caught = total = 0
    examples = []
    for it in items:
        if it.check["state"] == "blocked":
            continue
        d = it.data
        nums = verify.numbers(d.get("dose", "") or d.get("when", "") or d.get("instruction", "") or d.get("sign", ""))
        if nums:
            field = next(k for k in ("dose", "when", "instruction", "sign") if d.get(k) and nums[0] in d[k])
            bad = copy.deepcopy(d)
            n = nums[0]
            wrong = str(int(float(n) * 2)) if float(n) >= 1 else "1"
            bad[field] = bad[field].replace(n, wrong, 1)
            total += 1
            r = verify.check_item(it.kind, bad, doc)
            hit = r["state"] == "blocked"
            caught += hit
            if len(examples) < 3:
                examples.append({"field": field, "from": d[field], "to": bad[field], "caught": hit})
        # invented instruction: a quote that is not in the document
        bad = copy.deepcopy(d)
        bad["source_quote"] = (d.get("source_quote", "") + " Take two extra doses if you feel unwell.")
        total += 1
        caught += verify.check_item(it.kind, bad, doc)["state"] == "blocked"
    return {"caught": caught, "total": total, "examples": examples}


def translation_mutation(items: list[pipeline.Item]) -> dict:
    caught = total = 0
    for it in items:
        if it.kind != "medication" or not it.patient or it.translation_issues:
            continue
        nums = verify.numbers(it.data.get("dose", ""))
        if not nums:
            continue
        n = nums[0]
        wrong = str(int(float(n) * 10))
        bad_patient = re.sub(re.escape(n), wrong, it.patient, count=1)
        total += 1
        probs = verify.check_translation(it.data, it.plain_en, bad_patient, it.back_en, it.data.get("name"))
        caught += bool(probs)
    return {"caught": caught, "total": total}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--langs", nargs="+", default=["uk", "fr", "es", "zh"])
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    llm = LLM.from_env()
    docs = load_docs()
    t0 = time.time()

    def one_doc(doc_id: str):
        sc = scrub(docs[doc_id])
        ex = pipeline.extract(llm, sc.text)
        return doc_id, sc, ex

    with ThreadPoolExecutor(a.workers) as pool:
        extracted = list(pool.map(one_doc, docs))

    def one_lang(args):
        doc_id, sc, ex, lang = args
        items = pipeline._items_from_extract(ex, sc.text)
        pipeline.explain(llm, items, lang)
        pipeline.backcheck(llm, items, lang)
        return doc_id, lang, sc, items

    jobs = [(d, sc, ex, lang) for d, sc, ex in extracted for lang in a.langs]
    with ThreadPoolExecutor(a.workers) as pool:
        runs = list(pool.map(one_lang, jobs))
    wall = time.time() - t0

    per_doc, per_lang = {}, {l: {"items": 0, "clean": 0} for l in a.langs}
    mut = {"caught": 0, "total": 0}
    tmut = {"caught": 0, "total": 0}
    states = {"ok": 0, "review": 0, "blocked": 0}
    risk_items = 0
    examples = []
    for doc_id, lang, sc, items in runs:
        if lang == a.langs[0]:
            m = score_meds(doc_id, items)
            mt = mutation_test(sc.text, items)
            per_doc[doc_id] = {"meds": m, "states": {s: sum(1 for i in items if i.check["state"] == s)
                                                     for s in ("ok", "review", "blocked")},
                               "items": len(items), "scrubbed": sc.counts}
            for k in mut:
                mut[k] += mt[k]
            examples += mt["examples"][:1]
            for i in items:
                states[i.check["state"]] += 1
                risk_items += bool(i.check["risk"])
        tm = translation_mutation(items)
        for k in tmut:
            tmut[k] += tm[k]
        for i in items:
            if i.check["state"] == "blocked":
                continue
            per_lang[lang]["items"] += 1
            per_lang[lang]["clean"] += not i.translation_issues

    tot = {k: sum(d["meds"][k] for d in per_doc.values()) for k in ("gt", "extracted", "tp", "dose_ok", "status_ok", "status_n")}
    calls = [s for s in llm.stats]
    comp = sum(s.completion_tokens for s in calls)
    prompt = sum(s.prompt_tokens for s in calls)
    res = {
        "backend": llm.backend_label, "model": llm.model, "mode": llm.mode,
        "docs": len(docs), "languages": a.langs, "wall_seconds": round(wall, 1),
        "calls": len(calls), "prompt_tokens": prompt, "completion_tokens": comp,
        "completion_tokens_per_s_aggregate": round(comp / wall, 1) if wall else None,
        "median_call_latency_s": sorted(s.latency_s for s in calls)[len(calls) // 2] if calls else None,
        "medications": {**tot,
                        "recall": round(tot["tp"] / tot["gt"], 3),
                        "precision": round(tot["tp"] / tot["extracted"], 3) if tot["extracted"] else None,
                        "dose_exact": round(tot["dose_ok"] / tot["tp"], 3) if tot["tp"] else None,
                        "status_accuracy": round(tot["status_ok"] / tot["status_n"], 3) if tot["status_n"] else None},
        "item_states_first_lang": states, "items_with_risk_flags": risk_items,
        "mutation_test": {**mut, "rate": round(mut["caught"] / mut["total"], 3) if mut["total"] else None,
                          "examples": examples},
        "translation_mutation_test": {**tmut, "rate": round(tmut["caught"] / tmut["total"], 3) if tmut["total"] else None},
        "translation_clean_rate": {l: round(v["clean"] / v["items"], 3) if v["items"] else None for l, v in per_lang.items()},
        "per_doc": per_doc,
        "run_at": time.strftime("%Y-%m-%d %H:%M %Z"),
    }
    (ROOT / "eval" / "results.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in res.items() if k != "per_doc"}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
