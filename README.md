# Clearsheet

Discharge instructions a patient can follow, in their own language, with every line traced back
to the hospital's discharge summary and released by a nurse.

Built for the AMD Developer Hackathon ACT III (Health and Wellbeing track). Gemma runs on an
AMD Instinct MI300X with vLLM on ROCm.

## The problem

Patients leave hospital with a dense discharge summary written for clinicians: `Furosemide 40 mg
PO BID (INCREASED from 20 mg daily)`, `Hold if heart rate below 55`, `q4h PRN`. Many of them
read English as a second language. Nurses explain it at the bedside in a few minutes, often
through a phone interpreter, and the paper goes home unchanged.

A language model can rewrite and translate that page in seconds. It can also change a dose, drop
a "stop taking", or invent a warning, and nobody at the bedside can check a Ukrainian or Arabic
sheet line by line. Clearsheet is built around that second problem.

## How it works

```
discharge summary
  │  1. scrub (local, regex): names, MRN, health card, DOB, phone, email, address → [NAME_1] …
  ▼
Gemma on AMD MI300X ── 2. extract: medicines, follow-ups, warning signs, self-care.
  │                       Every fact carries a verbatim source quote.
  ▼
deterministic checks ── 3. quote must exist in the document; every number in the fact must be
  │                       inside its quote; high-alert medicines (ISMP classes), stops and
  │                       dose changes always go to a nurse.
  ▼
Gemma on AMD MI300X ── 4. plain English (about grade 6) + the patient's language
  │                    5. literal back-translation into English for the nurse
  ▼
deterministic checks ── 6. numbers the patient reads must come from the source; the dose
  │                       must survive translation; the drug name must survive.
  ▼
nurse review console ── 7. verified lines are pre-released; flagged lines need a click;
  │                       blocked lines stay off the sheet unless the nurse writes them.
  ▼
printable patient sheet (patient language first, English under it, dosette-style schedule)
```

The model drafts. Code decides what is allowed to reach the patient. The nurse decides the rest.

Known limits: the eight cases are synthetic and written by us; the checks are rules, so they catch numbers,
names, quotes and urgency words, and leave meaning to the nurse (who sees the back-translation). When the model
does not extract a separate emergency action line, the sheet prints the document's own lead-in sentence in English.

What it does not do: diagnose, recommend treatment, change doses, or add advice that is not in
the discharge summary. The sheet says so in its footer.

## Measured results

See `eval/results.json` (written by `python -m eval.run_eval`) and `eval/bench.json`
(`python -m eval.bench`). The numbers below are copied from those files.

Run: 2026-10-15 13:05 EDT, gemma-3-27b-it on AMD Instinct MI300X (gfx942) · vLLM 0.7.4 V1 engine, ROCm 6.3 · AMD AI Notebooks. 8 synthetic discharge summaries
× 6 languages (uk, fr, es, zh, ar, en), 96 model calls,
165,033 tokens.

| What we measured | Result |
|---|---|
| Medicines found (vs. hand annotation) | 97% (34 of 35) |
| Invented medicines | 0 (the 4 extra rows are prednisone taper steps) |
| Found medicines with the exact dose | 100% (34 of 34) |
| new / changed / stopped labelled right | 94% (16 of 17) |
| Injected wrong numbers and invented quotes blocked | 99% (173 of 175); the 2 misses are steps of a prednisone taper, which is always sent to a nurse |
| Wrong doses planted in translations flagged | 100% (189 of 189) |
| Emergency lines softened to "tell your doctor" flagged | 100% (120 of 120) |
| Translated lines with no automatic flag | uk 91% · fr 96% · es 95% · zh 96% · ar 95% · en 97% |

Throughput of the extraction step on one MI300X (gemma-3-27b-it, bf16, vLLM V1 engine on ROCm), `eval/bench.json`:

| Parallel requests | Output tokens/s | Summaries/min | p50 latency |
|---|---|---|---|
| 1 | 40.7 | 2.9 | 20.6 s |
| 8 | 218.2 | 15.5 | 22.3 s |
| 32 | 702.6 | 49.8 | 27.6 s |
| 64 | 1118.0 | 79.6 | 35.5 s |

Two catches from real runs on the MI300X:

- First prompt version: Gemma translated "call 911" into Ukrainian as "call 103", the ambulance number in Ukraine.
  The translation check flagged every such line (a number not in the source). We then added a prompt rule; the check stays.
- In the same first version, Gemma rewrote "Seek emergency care if: black or bloody stools" as "Tell your doctor if
  you have black or bloody stools", and our checks of that day passed it. That is why the urgency check exists: an
  emergency line that comes back as "tell your doctor", "see your GP" or "get medical care" is now flagged.

## Run it

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn clearsheet.server:app --port 8090        # replay mode: recorded MI300X responses
```

Live mode against any OpenAI-compatible endpoint (vLLM on AMD Developer Cloud, an AMD AI
Notebooks pod, or AMD Token Factory):

```bash
export CLEARSHEET_BASE_URL=https://<endpoint>/v1
export CLEARSHEET_API_KEY=...
export CLEARSHEET_MODEL=gemma-3-27b-it
uvicorn clearsheet.server:app --port 8090
```

Serving Gemma on an MI300X (what we ran):

```bash
VLLM_USE_V1=1 vllm serve unsloth/gemma-3-27b-it --dtype bfloat16 --max-model-len 16384
```

Docker: `docker build -t clearsheet . && docker run -p 3000:3000 clearsheet`

Tests (no model needed): `pytest -q`

## Data

All eight discharge summaries in `samples/` are synthetic and written for this project. They are
marked as fictional on their first line. No real patient data was used anywhere.

## License

MIT
