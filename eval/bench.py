"""Throughput of the extraction step on one GPU at different batch sizes.

python -m eval.bench --conc 1 8 32   (needs a live endpoint in env)
Writes eval/bench.json. Each request is a real extraction prompt for one of
the 8 synthetic discharge summaries (cycled).
"""
from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from openai import OpenAI

from clearsheet.llm import merge_system
from clearsheet.pipeline import EXTRACT_SYSTEM
from clearsheet.scrub import scrub

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--conc", type=int, nargs="+", default=[1, 8, 32])
    a = ap.parse_args()
    client = OpenAI(base_url=os.environ["CLEARSHEET_BASE_URL"], api_key=os.environ.get("CLEARSHEET_API_KEY", "none"), timeout=600)
    model = os.environ.get("CLEARSHEET_MODEL", "gemma-3-27b-it")
    docs = [scrub(p.read_text()).text for p in sorted((ROOT / "samples").glob("*.txt"))]

    def one(i: int):
        msgs = merge_system([{"role": "system", "content": EXTRACT_SYSTEM},
                             {"role": "user", "content": "Discharge document:\n\n" + docs[i % len(docs)]}])
        t = time.time()
        r = client.chat.completions.create(model=model, messages=msgs, temperature=0, max_tokens=1500)
        return time.time() - t, r.usage.prompt_tokens, r.usage.completion_tokens

    out = []
    for c in a.conc:
        n = max(c, 8)
        t0 = time.time()
        with ThreadPoolExecutor(c) as pool:
            res = list(pool.map(one, range(n)))
        wall = time.time() - t0
        comp = sum(r[2] for r in res)
        row = {"concurrency": c, "requests": n, "wall_s": round(wall, 1),
               "output_tokens": comp, "output_tok_per_s": round(comp / wall, 1),
               "docs_per_min": round(n / wall * 60, 1),
               "p50_latency_s": round(sorted(r[0] for r in res)[n // 2], 1)}
        print(row, flush=True)
        out.append(row)
    meta = {"model": model, "backend": os.environ.get("CLEARSHEET_BACKEND_LABEL", ""), "rows": out,
            "run_at": time.strftime("%Y-%m-%d %H:%M %Z")}
    (ROOT / "eval" / "bench.json").write_text(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
