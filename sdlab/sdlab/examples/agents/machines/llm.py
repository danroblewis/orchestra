"""An AI agent as a machine: a general-purpose program whose parameters are a prompt.

The runner gives it, on stdin, the items it took, the stocks it may write to ("to"), a glance at
the stocks around it ("context": each one's level and a few recent items), and the machine's
prompt. It asks a language model what to do and writes one {"to": <stock>, "item": {...}} per
line, like any other program. If the model's answer has no usable line, it exits non-zero and
the runner puts the items back.

The model is any OpenAI-compatible chat endpoint: SDLAB_LLM_URL (default the local server on
http://127.0.0.1:8081/v1) and SDLAB_LLM_MODEL (default: the first model it lists).

    llm.py [--temperature 0.2] [--max-tokens 600]
"""

import argparse
import json
import os
import re
import sys
import urllib.request

URL = os.environ.get("SDLAB_LLM_URL", "http://127.0.0.1:8081/v1").rstrip("/")


def call(path, body=None, timeout=170):
    req = urllib.request.Request(URL + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def model_name():
    if os.environ.get("SDLAB_LLM_MODEL"):
        return os.environ["SDLAB_LLM_MODEL"]
    listed = call("/models", timeout=10)
    items = listed.get("data") or listed.get("models") or []
    return (items[0].get("id") or items[0].get("model") or items[0].get("name")) if items else "default"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--max-tokens", type=int, default=600)
    args, _ = ap.parse_known_args()
    job = json.load(sys.stdin)
    allowed = [t for t in job.get("to", [])]
    names = {sid: c.get("name", sid) for sid, c in (job.get("context") or {}).items()}
    targets = ", ".join(f'"{t}" ({names.get(t, t)})' if t else "null (the item leaves the system)" for t in allowed)

    system = (
        "You are one machine in a system of stocks and flows. Each time you run, you are handed some items "
        "taken from a stock, and you decide what to make from them and which stock each result goes to. "
        "Answer only with JSON lines, one per item you make, each exactly like "
        '{"to": "<stock id>", "item": {...fields...}}. '
        f"Allowed values for \"to\": {targets}. Make at least one item. No other text."
    )
    user = (
        f"Your job ({job.get('flow_name', job.get('flow'))}):\n{job.get('prompt') or 'Do the obvious thing with these items.'}\n\n"
        f"Items you were given:\n{json.dumps(job.get('inputs', {}), indent=1)}\n\n"
        f"The stocks around you right now:\n{json.dumps(job.get('context', {}), indent=1)}"
    )
    reply = call("/chat/completions", {
        "model": model_name(), "temperature": args.temperature, "max_tokens": args.max_tokens,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    })
    text = (reply.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    text = re.sub(r"```(?:json)?", "", text)
    made = 0
    for line in text.splitlines():
        line = line.strip().rstrip(",")
        if not line.startswith("{"):
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or rec.get("to") not in allowed or not isinstance(rec.get("item", {}), dict):
            continue
        print(json.dumps({"to": rec["to"], "item": rec.get("item", {})}))
        made += 1
    if not made:
        sys.exit("the language model's answer had no usable line: " + text[:300].replace("\n", " "))


if __name__ == "__main__":
    main()
