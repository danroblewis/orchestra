"""Rules triage: the keyword rules a support desk writes before it has an AI agent.

It takes one message (input "item") and routes it to one of the stocks the flow may fill, checking
rules in order: spam words, then words for something broken, then money words, then question
words. How-to questions get a canned reply pointing at the help centre. Anything no rule
matches goes to engineering, where a person will look at it.

    rules.py [--billing billing] [--engineering engineering] [--answered answered] [--spam spam]
"""

import argparse
import json
import sys

SPAM = ["seo", "backlinks", "winner", "won a free", "click here", "crypto", "prize"]
BROKEN = ["crash", "error", "not working", "not syncing", "doesn't work", "broken", "grey boxes", "spins forever", "fails"]
MONEY = ["charge", "refund", "invoice", "payment", "billing", "subscription", "price", "cancel"]
QUESTION = ["how do i", "how can i", "how to", "is there a way"]


def main():
    ap = argparse.ArgumentParser()
    for stock in ("billing", "engineering", "answered", "spam"):
        ap.add_argument(f"--{stock}", default=stock)
    args, _ = ap.parse_known_args()
    job = json.load(sys.stdin)
    msg = (job.get("inputs") or {}).get("item", {})
    words = f"{msg.get('subject', '')} {msg.get('text', '')}".lower()
    keep = {k: msg[k] for k in ("from", "subject", "text") if k in msg}

    def hit(keys):
        return next((k for k in keys if k in words), None)

    if k := hit(SPAM):
        to, extra = args.spam, {"category": "spam", "reason": f"keyword '{k}'"}
    elif k := hit(BROKEN):
        to, extra = args.engineering, {"category": "bug", "reason": f"keyword '{k}'"}
    elif k := hit(MONEY):
        to, extra = args.billing, {"category": "billing", "reason": f"keyword '{k}'"}
    elif k := hit(QUESTION):
        to, extra = args.answered, {"category": "howto", "reason": f"keyword '{k}'",
                                    "answer": "Thanks for asking! Step-by-step guides are at help.lumen.example; search for your question there."}
    else:
        to, extra = args.engineering, {"category": "unknown", "reason": "no rule matched; a person will look"}
    if to not in job.get("to", [to]):
        sys.exit(f"this flow cannot fill {to!r}; name the right stock with --billing/--engineering/--answered/--spam")
    print(json.dumps({"to": to, "item": {**keep, **extra, "triaged_by": "rules"}}))


if __name__ == "__main__":
    main()
