"""Stage 4/5: classify replies and route. Closer drafts are queued for a human; nothing here sends."""
from __future__ import annotations

import re

from ..compliance import footer
from ..context import Ctx
from ..models import Draft

LABELS = ["positive", "question", "pricing_objection", "technical_objection", "not_now", "referral", "unsubscribe", "other"]
UNSUB = re.compile(r"\b(unsubscribe|remove me|stop (emailing|contacting)|do not contact|don't contact)\b", re.I)


def retrieve_kb(kb: str, text: str, k: int = 2) -> list[str]:
    """Tiny keyword RAG over kb.md sections (## title / tags: ... / body)."""
    text = text.lower()
    scored = []
    for sec in re.split(r"^## ", kb, flags=re.M)[1:]:
        lines = sec.strip().splitlines()
        tags = [t.strip() for t in lines[1].replace("tags:", "").split(",")] if len(lines) > 1 else []
        score = sum(1 for t in tags if t and t in text)
        if score:
            scored.append((score, "\n".join(lines[2:]).strip()))
    return [b for _, b in sorted(scored, key=lambda x: -x[0])[:k]]


def classify(ctx: Ctx, lead_id: str, text: str) -> str:
    if UNSUB.search(text):  # compliance rule beats any model
        return "unsubscribe"
    r = ctx.llm.json("classify_reply", f"Classify the reply into one of {LABELS}. " 'Return {"label": str}.', {"reply": text}, tier="cheap")
    return r["label"] if r.get("label") in LABELS else "other"


def handle(ctx: Ctx, lead_id: str, text: str) -> dict:
    lead = ctx.mem.get_lead(lead_id)
    label = classify(ctx, lead_id, text)
    action, draft_id = "none", None
    for d in ctx.mem.drafts(status="pending", lead_id=lead_id):  # a human replied: cancel queued automated touches
        if d.kind == "touch":
            ctx.mem.update_draft(d.id, status="rejected")
    if label == "unsubscribe":
        if lead.email:
            ctx.mem.suppress(lead.email, "unsubscribe reply")
        ctx.mem.set_status(lead_id, "unsubscribed"); action = "suppressed"
    elif label == "not_now":
        ctx.mem.set_status(lead_id, "snoozed"); action = "snoozed"
    elif label == "referral":
        ctx.mem.set_status(lead_id, "referral"); action = "human_follow_up"
    else:
        ctx.mem.set_status(lead_id, "replied")
        kb = retrieve_kb(ctx.kb, text) if label in ("question", "pricing_objection", "technical_objection") else []
        r = ctx.llm.json(
            "draft_reply",
            "You are the Closer. Draft a reply to the prospect's message. Answer ONLY from kb_snippets and product_facts. If they do not cover the "
            "question, say you'd rather confirm on a call than guess. Never quote prices or results. For a positive reply, propose a short call. "
            'Return {"body": str}.',
            {"label": label, "reply": text, "kb_snippets": kb, "product_facts": ctx.product_facts, "memory": ctx.mem.recall(lead_id)}, tier="top")
        n = len(ctx.mem.replies(lead_id)) + 1
        d = Draft(lead_id=lead_id, thread_id=f"{lead_id}:reply:{n}", kind="reply", step=0, channel="email",
                  subject="Re: " + (next((x.subject for x in ctx.mem.drafts(lead_id=lead_id) if x.kind == "touch" and x.subject), "your note")),
                  body=r["body"].strip() + footer(ctx.cfg), evidence_ids=[])
        draft_id = ctx.mem.add_draft(d); action = "reply_drafted"
    ctx.mem.add_reply(lead_id, text, label, action)
    ctx.log(lead_id, "inbox", "reply", {"label": label, "action": action, "draft_id": draft_id})
    return {"label": label, "action": action, "draft_id": draft_id}


def register_fake(llm) -> None:
    def cls(p: dict) -> dict:
        t = p["reply"].lower()
        rules = [("pricing_objection", ("price", "pricing", "cost", "how much", "expensive")),
                 ("not_now", ("not now", "next quarter", "later", "busy")),
                 ("referral", ("talk to", "reach out to", "forward", "right person")),
                 ("technical_objection", ("integrat", "security", "data", "api")),
                 ("positive", ("interested", "let's talk", "sounds good", "book", "send times", "yes")),
                 ("question", ("?", "how does", "what is"))]
        for label, kws in rules:
            if any(k in t for k in kws):
                return {"label": label}
        return {"label": "other"}

    def reply(p: dict) -> dict:
        if p["label"] == "positive":
            return {"body": "Great to hear. Would a 20-minute call this week work? Send a couple of times that suit you and I'll confirm."}
        if p["kb_snippets"]:
            return {"body": p["kb_snippets"][0] + " Happy to walk through it on a short call."}
        return {"body": "Good question. I'd rather confirm that on a call than guess. Would a short call this week work?"}

    llm.register("classify_reply", cls)
    llm.register("draft_reply", reply)
