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

What it does not do: diagnose, recommend treatment, change doses, or add advice that is not in
the discharge summary. The sheet says so in its footer.

## Measured results

See `eval/results.json` (written by `python -m eval.run_eval`) and `eval/bench.json`
(`python -m eval.bench`). The numbers below are copied from those files.

RESULTS_PLACEHOLDER

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
