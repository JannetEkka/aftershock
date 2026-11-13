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
# Two different model families. The Examiner of a claim is always the family that did NOT write it.
MODELS = {"glm": "z-ai/glm-5.3-flash", "nemotron": "nvidia/nemotron-3-ultra-550b-a55b"}
OTHER = {"glm": "nemotron", "nemotron": "glm"}

calls = []   # log of every call in this run: role, family, attempt, valid, error
used = set()  # reply files used in this run


class ReplayMissing(Exception):
    pass


def mode():
    return os.environ.get("AFTERSHOCK_MODE", "replay")


def _path(role, family, system, user, attempt):
    key = hashlib.sha256(json.dumps([MODELS[family], system, user, attempt]).encode()).hexdigest()[:16]
    return os.path.join(REPLIES, f"{role}-{key}.json")


def chat(role, family, system, user, attempt=0, max_tokens=16000):
    """Return the model's reply text. Reads the recording if there is one; calls the API only in live mode."""
    path = _path(role, family, system, user, attempt)
    used.add(os.path.basename(path))
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)["reply"]
    if mode() != "live":
        raise ReplayMissing(f"no recorded reply for role '{role}' ({os.path.basename(path)}). "
                            "The snapshot or the prompts changed since the recording; run `make live` with a key.")
    # Streamed, because long answers otherwise hit the gateway's 30-second limit. Reasoning tokens are dropped.
    body = json.dumps({"model": MODELS[family], "temperature": 0, "max_tokens": max_tokens, "stream": True,
                       "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}).encode()
    key = os.environ.get("NVIDIA_API_KEY")
    if not key:
        raise SystemExit("STOPPED: live mode needs NVIDIA_API_KEY (a free key from build.nvidia.com).")
    err = None
    for i in range(5):
        try:
            req = urllib.request.Request(URL, data=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            parts = []
            with urllib.request.urlopen(req, timeout=600) as r:
                for line in r:
                    line = line.decode("utf-8", "replace").strip()
                    if not line.startswith("data:") or line == "data: [DONE]":
                        continue
                    ch = json.loads(line[5:]).get("choices") or [{}]
                    parts.append((ch[0].get("delta") or {}).get("content") or "")
            reply = "".join(parts)
            break
        except Exception as e:
            err = e
            time.sleep(10 * (i + 1))
    else:
        raise SystemExit(f"STOPPED: model call for role '{role}' failed 5 times: {err!r}")
    os.makedirs(REPLIES, exist_ok=True)
    with open(path, "w") as f:
        json.dump({"role": role, "model": MODELS[family], "attempt": attempt, "system": system, "user": user, "reply": reply}, f, indent=1)
        f.write("\n")
    return reply


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


def ask_json(role, family, system, user, validate, max_tokens=16000):
    """Ask for JSON and validate it. `validate(obj)` returns an error string or None.
    An invalid reply is retried once with the error shown; a second failure returns None."""
    error = None
    for attempt in (0, 1):
        prompt = user if attempt == 0 else f"{user}\n\nYour previous reply was rejected by the validator: {error}\nReply again with valid JSON only."
        obj = extract_json(chat(role, family, system, prompt, attempt, max_tokens))
        error = "reply is not a JSON object" if obj is None else validate(obj)
        calls.append({"role": role, "family": family, "model": MODELS[family], "attempt": attempt, "valid": error is None, "error": error})
        if error is None:
            return obj
    return None


def prune():
    """Live mode only: delete recordings this run did not use, so replies/ matches the run exactly."""
    for f in os.listdir(REPLIES):
        if f.endswith(".json") and f not in used:
            os.remove(os.path.join(REPLIES, f))
