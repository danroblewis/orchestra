"""The support desk around the triage step: messages arriving, and people working the queues off.

The product is Lumen, a photo-storage app. Messages carry no label saying what kind they are:
deciding that is the Triage flow's job. TEMPLATES says which kind each one really is, and
`which(text)` recognises a message's template again, so tests and reviewers can score a triage.
Templates marked tricky are ones a keyword rule gets wrong (a billing complaint that mentions a
crash, phishing that mentions an invoice, a how-to without the word "how").

    desk.py arrive        a new customer message from outside (no inputs)
    desk.py settle        the billing clerk resolves one billing message
    desk.py fix           the engineer resolves one bug report
"""

import argparse
import json
import random
import re
import sys

NAMES = ["maria.k", "tom.b", "aisha", "j.lindqvist", "chen.wei", "pat_o", "dmitri", "sofia.r", "kwame", "lea.m"]
DOMAINS = ["example.com", "mail.example.org", "inbox.example.net"]
DEVICES = ["iPhone", "Pixel", "iPad", "Windows laptop", "MacBook", "Galaxy tablet"]
PLANS = ["Plus", "Family", "Pro"]
AMOUNTS = ["4.99", "9.99", "19.99", "59.88"]
COUNTS = ["12", "40", "200", "1,300"]

# (kind, tricky, subject, text); {device} {plan} {amount} {count} are filled in at random
TEMPLATES = [
    ("billing", False, "Charged twice this month", "Hi, I was charged ${amount} twice for my {plan} subscription this month. Can you refund one of them?"),
    ("billing", False, "Cancel my subscription", "Please cancel my {plan} plan and stop billing my card. I don't want it to renew."),
    ("billing", False, "Need an invoice", "Could you send me an invoice for the ${amount} payment? My company needs it for expenses."),
    ("billing", False, "Wrong price", "Your site said {plan} was ${amount} but my card was charged more. Why the difference?"),
    ("billing", True, "Paid but still on free", "The app crashed during checkout on my {device}. My card shows ${amount} taken but I'm still on the free tier."),
    ("bug", False, "App crashes on upload", "Every time I upload more than {count} photos from my {device} the app crashes."),
    ("bug", False, "Sync not working", "Photos taken on my {device} are not syncing anymore. The sync icon just spins forever."),
    ("bug", False, "Error when sharing", "I get 'Error 500' whenever I try to share an album from the {device} app."),
    ("bug", False, "Thumbnails broken", "Since the last update all thumbnails on my {device} are grey boxes. The full photos open fine."),
    ("bug", True, "Where are my albums?", "Where did all my albums go? I logged in on my {device} this morning and the library is empty. How do I get my {count} photos back?"),
    ("howto", False, "How do I make an album?", "How do I make a shared album that my family can add photos to?"),
    ("howto", False, "Download everything", "How can I download all my photos at once to my {device}?"),
    ("howto", False, "Upload over Wi-Fi only", "How do I stop the {device} app from uploading over mobile data?"),
    ("howto", True, "Sharing with non-users", "Is it possible to share an album with my grandmother? She doesn't have a Lumen account."),
    ("howto", True, "Free up space", "My {device} is full. Can I delete photos from the phone and still keep them in Lumen?"),
    ("spam", False, "Boost your SEO today", "We can get your website to page one of Google with 500 quality backlinks. Reply for a free SEO audit!"),
    ("spam", False, "You are a WINNER", "Congratulations!!! You have won a free {device}. Click here to claim your prize before midnight."),
    ("spam", False, "Crypto opportunity", "Earn 30% a week with our crypto trading bot. Limited spots, click here to join."),
    ("spam", True, "Invoice #4471 overdue", "Your invoice #4471 for ${amount} is overdue. Open http://lumen-billing.example.top/pay to update your payment details now."),
]
WEIGHTS = {"billing": 0.3, "bug": 0.25, "howto": 0.25, "spam": 0.2}
SLOTS = {"device": DEVICES, "plan": PLANS, "amount": AMOUNTS, "count": COUNTS}


def fill(text):
    return re.sub(r"\{(\w+)\}", lambda m: random.choice(SLOTS[m.group(1)]), text)


def which(text):
    """The template a message was made from, as (kind, tricky), or None."""
    for kind, tricky, _, tpl in TEMPLATES:
        pattern = "".join(".+?" if p.startswith("{") else re.escape(p) for p in re.split(r"(\{\w+\})", tpl))
        if re.fullmatch(pattern, text or ""):
            return kind, tricky
    return None


def emit(to, item):
    print(json.dumps({"to": to, "item": item}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task", choices=["arrive", "settle", "fix"])
    args, _ = ap.parse_known_args()
    job = json.load(sys.stdin)
    msg = (job.get("inputs") or {}).get("item", {})
    keep = {k: v for k, v in msg.items() if not k.startswith("_")}     # what triage wrote travels on

    if args.task == "arrive":
        kind = random.choices(list(WEIGHTS), weights=list(WEIGHTS.values()))[0]
        _, _, subject, text = random.choice([t for t in TEMPLATES if t[0] == kind])
        sender = f"{random.choice(NAMES)}@{random.choice(DOMAINS)}" if kind != "spam" else f"promo{random.randint(10, 99)}@{random.choice(DOMAINS)}"
        emit("inbox", {"from": sender, "subject": subject, "text": fill(text)})

    elif args.task == "settle":
        text = msg.get("text", "").lower()
        if "cancel" in text:
            outcome = "subscription cancelled, no further charges"
        elif "invoice" in text:
            outcome = "invoice sent"
        elif "twice" in text or "free tier" in text:
            outcome = "duplicate charge refunded" if "twice" in text else "plan upgraded to match the payment"
        else:
            outcome = "explained the charge"
        emit("resolved", {**keep, "team": "billing", "outcome": outcome})

    elif args.task == "fix":
        outcome = random.choice(["fixed in the next release", "workaround sent", "known issue, customer told", "could not reproduce, asked for logs"])
        emit("resolved", {**keep, "team": "engineering", "outcome": outcome})


if __name__ == "__main__":
    main()
