"""OpenAI-compatible chat client with a record/replay cache.

Backends (all speak the OpenAI chat API):
  * vLLM on an AMD Instinct MI300X (ROCm), e.g. an AMD Developer Cloud or
    AMD AI Notebooks pod, serving Gemma 3.
  * AMD Token Factory (the hosted inference endpoint for the hackathon).
  * replay: answers from responses recorded during a live run, so the demo
    keeps working after the GPU pod is gone. Replay never invents an answer:
    a request that was not recorded raises ReplayMiss.

Config via env: CLEARSHEET_BASE_URL, CLEARSHEET_API_KEY, CLEARSHEET_MODEL,
CLEARSHEET_BACKEND_LABEL, CLEARSHEET_MODE (live|replay|auto, default auto).
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

CACHE_PATH = Path(os.environ.get(
    "CLEARSHEET_CACHE", Path(__file__).resolve().parent.parent / "recordings" / "calls.jsonl"))


class ReplayMiss(RuntimeError):
    pass


@dataclass
class CallStat:
    step: str
    latency_s: float
    prompt_tokens: int
    completion_tokens: int
    backend: str
    model: str
    replayed: bool


@dataclass
class LLM:
    base_url: str | None = None
    api_key: str | None = None
    model: str = "gemma-3-27b-it"
    backend_label: str = "replay"
    mode: str = "auto"
    guided_json: bool = True
    stats: list[CallStat] = field(default_factory=list)
    _cache: dict | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def from_env(cls) -> "LLM":
        base = os.environ.get("CLEARSHEET_BASE_URL") or None
        mode = os.environ.get("CLEARSHEET_MODE", "auto")
        if mode == "auto":
            mode = "live" if base else "replay"
        return cls(
            base_url=base,
            api_key=os.environ.get("CLEARSHEET_API_KEY", "none"),
            model=os.environ.get("CLEARSHEET_MODEL", "gemma-3-27b-it"),
            backend_label=os.environ.get("CLEARSHEET_BACKEND_LABEL",
                                         "AMD Instinct MI300X · vLLM (ROCm)" if base else "replay"),
            mode=mode,
            guided_json=os.environ.get("CLEARSHEET_GUIDED_JSON", "1") == "1",
        )

    # ---- cache -------------------------------------------------------
    def _load(self) -> dict:
        if self._cache is None:
            self._cache = {}
            if CACHE_PATH.exists():
                for line in CACHE_PATH.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        rec = json.loads(line)
                        self._cache[rec["key"]] = rec
        return self._cache

    @staticmethod
    def key(model: str, messages: list[dict], schema: dict | None, temperature: float) -> str:
        blob = json.dumps({"m": model, "msg": messages, "s": schema, "t": temperature},
                          sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()

    # ---- call --------------------------------------------------------
    def chat(self, step: str, messages: list[dict], schema: dict | None = None,
             temperature: float = 0.0, max_tokens: int = 3000) -> str:
        messages = merge_system(messages)
        k = self.key(self.model, messages, schema if self.guided_json else None, temperature)
        cache = self._load()
        if self.mode == "replay":
            rec = cache.get(k)
            if rec is None:
                raise ReplayMiss(f"no recorded response for step '{step}'")
            self.stats.append(CallStat(step, rec["latency_s"], rec["usage"].get("prompt_tokens", 0),
                                       rec["usage"].get("completion_tokens", 0),
                                       rec.get("backend", "?"), rec.get("model", self.model), True))
            return rec["content"]

        from openai import OpenAI  # imported lazily so replay mode needs no network
        client = OpenAI(base_url=self.base_url, api_key=self.api_key or "none", timeout=300)
        kwargs: dict = dict(model=self.model, messages=messages, temperature=temperature,
                            max_tokens=max_tokens)
        if schema is not None and self.guided_json:
            kwargs["extra_body"] = {"guided_json": schema}
            if os.environ.get("CLEARSHEET_GUIDED_BACKEND"):
                kwargs["extra_body"]["guided_decoding_backend"] = os.environ["CLEARSHEET_GUIDED_BACKEND"]
        t0 = time.time()
        resp = client.chat.completions.create(**kwargs)
        dt = time.time() - t0
        content = resp.choices[0].message.content or ""
        usage = resp.usage.model_dump() if resp.usage else {}
        rec = {"key": k, "step": step, "model": self.model, "backend": self.backend_label,
               "latency_s": round(dt, 3), "usage": usage, "content": content,
               "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        with self._lock:
            cache[k] = rec
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with CACHE_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.stats.append(CallStat(step, dt, usage.get("prompt_tokens", 0),
                                   usage.get("completion_tokens", 0), self.backend_label,
                                   self.model, False))
        return content


def merge_system(messages: list[dict]) -> list[dict]:
    """Gemma chat templates have no system role: fold it into the first user turn."""
    if not messages or messages[0]["role"] != "system":
        return messages
    sys_msg, rest = messages[0]["content"], [dict(m) for m in messages[1:]]
    if rest and rest[0]["role"] == "user":
        rest[0]["content"] = sys_msg + "\n\n" + rest[0]["content"]
        return rest
    return [{"role": "user", "content": sys_msg}] + rest


def parse_json(text: str):
    """Parse a JSON object from a model reply (tolerates ```json fences)."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    start = min([i for i in (t.find("{"), t.find("[")) if i >= 0], default=0)
    return json.loads(t[start:])
