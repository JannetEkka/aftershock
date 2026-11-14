"""Model calls, recorded for replay.

Every reply is saved under replies/. `make replay` (AFTERSHOCK_MODE=replay, the default) only reads those
files: no key, no network. `make live` (AFTERSHOCK_MODE=live) calls build.nvidia.com with NVIDIA_API_KEY
and records what comes back, including replies that fail validation.
"""
import hashlib
import json
import os
import re
import time
import urllib.request

from .snapshot import ROOT

REPLIES = os.path.join(ROOT, "replies")
URL = "https://integrate.api.nvidia.com/v1/chat/completions"
# Two seats from different model families. The Examiner of a claim is always the seat that did NOT write it.
# "nvidia" is NVIDIA's own Nemotron. "open" is a model from another lab: the free endpoints go up and down,
# so the seat tries these in order and the recording stores which one answered.
SEATS = {"open": ["z-ai/glm-5.3-flash", "minimaxai/minimax-m3.1-flash", "stepfun-ai/step-5-preview"],
         "nvidia": ["nvidia/nemotron-3.5-lightning-30b-a3b"]}
OTHER = {"open": "nvidia", "nvidia": "open"}
DEADLINE = 600  # seconds allowed for one streamed reply before the next model is tried

calls = []   # log of every call in this run: role, family, attempt, valid, error
used = set()  # reply files used in this run


class ReplayMissing(Exception):
    pass


def mode():
    return os.environ.get("AFTERSHOCK_MODE", "replay")


def _path(role, seat, system, user, attempt):
    key = hashlib.sha256(json.dumps([seat, system, user, attempt]).encode()).hexdigest()[:16]
    return os.path.join(REPLIES, f"{role}-{key}.json")


def _stream(model, system, user, max_tokens, key):
    """One streamed call. Reasoning tokens are dropped; only the answer is kept."""
    body = json.dumps({"model": model, "temperature": 0, "max_tokens": max_tokens, "stream": True,
                       "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    parts, t0, done = [], time.time(), False
    with urllib.request.urlopen(req, timeout=120) as r:
        for line in r:
            line = line.decode("utf-8", "replace").strip()
            if line == "data: [DONE]":
                done = True
                break
            if line.startswith("data:"):
                ch = json.loads(line[5:]).get("choices") or [{}]
                parts.append((ch[0].get("delta") or {}).get("content") or "")
            if time.time() - t0 > DEADLINE:
                raise TimeoutError(f"no complete reply in {DEADLINE}s")
    reply = "".join(parts)
    if not done or not reply.strip():
        raise ValueError("stream ended without an answer")
    return reply


def chat(role, seat, system, user, attempt=0, max_tokens=16000):
    """Return (reply text, model that wrote it). Reads the recording if there is one; calls the API only in live mode."""
    path = _path(role, seat, system, user, attempt)
    used.add(os.path.basename(path))
    if os.path.exists(path):
        with open(path) as f:
            d = json.load(f)
        return d["reply"], d["model"]
    if mode() != "live":
        raise ReplayMissing(f"no recorded reply for role '{role}' ({os.path.basename(path)}). "
                            "The snapshot or the prompts changed since the recording; run `make live` with a key.")
    key = os.environ.get("NVIDIA_API_KEY")
    if not key:
        raise SystemExit("STOPPED: live mode needs NVIDIA_API_KEY (a free key from build.nvidia.com).")
    err = None
    for rnd in range(3):
        for model in SEATS[seat]:
            try:
                reply = _stream(model, system, user, max_tokens, key)
            except Exception as e:
                err = f"{model}: {e!r}"
                continue
            os.makedirs(REPLIES, exist_ok=True)
            with open(path, "w") as f:
                json.dump({"role": role, "seat": seat, "model": model, "attempt": attempt, "system": system, "user": user, "reply": reply}, f, indent=1)
                f.write("\n")
            return reply, model
        time.sleep(20 * (rnd + 1))
    raise SystemExit(f"STOPPED: model call for role '{role}' failed on every model of seat '{seat}': {err}")


def extract_json(text):
    """The first JSON object in a reply (models sometimes wrap it in ``` fences or prose). None if there is none."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except ValueError:
                        pass
                    break
        start = text.find("{", start + 1)
    return None


def ask_json(role, seat, system, user, validate, max_tokens=16000):
    """Ask for JSON and validate it. `validate(obj)` returns an error string or None.
    An invalid reply is retried once with the error shown; a second failure returns None."""
    error = None
    for attempt in (0, 1):
        prompt = user if attempt == 0 else f"{user}\n\nYour previous reply was rejected by the validator: {error}\nReply again with valid JSON only."
        reply, model = chat(role, seat, system, prompt, attempt, max_tokens)
        obj = extract_json(reply)
        error = "reply is not a JSON object" if obj is None else validate(obj)
        calls.append({"role": role, "seat": seat, "model": model, "attempt": attempt, "valid": error is None, "error": error})
        if error is None:
            obj["_model"] = model
        if error is None:
            return obj
    return None


def warm(jobs, workers=8):
    """Live mode only: make first-attempt calls in parallel so the slow part is not one long queue.
    `jobs` is a list of (role, seat, system, user). The normal, ordered pass then reads the recordings."""
    if mode() != "live" or not jobs:
        return
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(lambda j: chat(*j), jobs))


def prune():
    """Live mode only: delete recordings this run did not use, so replies/ matches the run exactly."""
    for f in os.listdir(REPLIES):
        if f.endswith(".json") and f not in used:
            os.remove(os.path.join(REPLIES, f))
