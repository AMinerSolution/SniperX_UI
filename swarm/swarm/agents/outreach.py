"""Stage 4: evidence-grounded drafts. Code validates grounding; code appends compliance footer."""
from __future__ import annotations

import re

from ..compliance import footer
from ..context import Ctx
from ..models import Draft

# (step, channel, days after previous touch) -> Day 1 / 4 / 7 / 12
SEQUENCE = [(1, "email", 0), (2, "email", 3), (3, "linkedin", 3), (4, "email", 5)]
BANNED = re.compile(r"guarantee|\bROI\b|risk[- ]free|\$\s?\d|\d\s?%", re.I)


class DraftRejected(Exception):
    pass


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", text))


def validate(body: str, subject: str, evidence_ids: list[int], evidence, product_facts: str, step: int, channel: str) -> list[str]:
    errs = []
    by_id = {e.id: e for e in evidence}
    if step <= 2 and not evidence_ids:
        errs.append("first touches must cite at least one evidence id")
    bad = [i for i in evidence_ids if i not in by_id]
    if bad:
        errs.append(f"unknown evidence ids {bad}")
    allowed = _numbers(product_facts + " " + " ".join(f"{e.claim} {e.quote}" for e in evidence))
    ungrounded = _numbers(subject + " " + body) - allowed
    if ungrounded:
        errs.append(f"numbers not found in evidence or product facts: {sorted(ungrounded)}")
    if BANNED.search(subject + " " + body):
        errs.append("contains banned claim language (price/ROI/guarantee)")
    limit = 60 if channel == "linkedin" else 120
    if len(body.split()) > limit:
        errs.append(f"body over {limit} words")
    return errs


def run(ctx: Ctx, lead_id: str, step: int) -> Draft:
    lead = ctx.mem.get_lead(lead_id)
    _, channel, _ = next(s for s in SEQUENCE if s[0] == step)
    evidence = ctx.mem.evidence(lead_id)
    prior = [{"step": d.step, "subject": d.subject, "body": d.body} for d in ctx.mem.drafts(lead_id=lead_id) if d.kind == "touch" and d.status == "sent"]
    payload = {"step": step, "channel": channel, "lead": lead.model_dump(exclude={"raw"}), "evidence": [e.model_dump() for e in evidence],
               "product_facts": ctx.product_facts, "prior_touches": prior, "fix": []}
    system = ("You write one cold outreach touch for a busy ecommerce ops leader. Use ONLY the evidence and product_facts provided; "
              "never invent company facts, numbers, prices, results or customers. Under 100 words, plain text, one soft ask. "
              "Step 2/4 reference the earlier touch; step 4 is a polite breakup; step 3 is a short LinkedIn note. "
              'Return {"subject": str, "body": str, "evidence_ids": [ids you relied on], "signal_used": str}. Do not add a signature or unsubscribe line.')
    for attempt in range(2):
        r = ctx.llm.json("draft_touch", system, payload, tier="mid")
        errs = validate(r["body"], r.get("subject", ""), r.get("evidence_ids", []), evidence, ctx.product_facts, step, channel)
        ctx.log(lead_id, "outreach", "draft_attempt", {"step": step, "attempt": attempt, "errors": errs})
        if not errs:
            break
        payload["fix"] = errs
    else:
        raise DraftRejected("; ".join(errs))
    body = r["body"].strip() + (footer(ctx.cfg) if channel == "email" else "")
    d = Draft(lead_id=lead_id, thread_id=f"{lead_id}:{step}", kind="touch", step=step, channel=channel,
              subject=r.get("subject", ""), body=body, evidence_ids=r["evidence_ids"])
    d.id = ctx.mem.add_draft(d)
    return d


def register_fake(llm) -> None:
    def draft(p: dict) -> dict:
        lead, ev = p["lead"], p["evidence"]
        first = (lead["contact_name"] or "").split(" ")[0]
        hi = f"Hi {first}," if first else "Hi there,"
        prio = {"pain": 0, "hiring": 1, "tech": 2}
        best = sorted(ev, key=lambda e: prio.get(e["kind"], 9))[0] if ev else None
        ids = [best["id"]] if best else []
        fact = best["claim"].rstrip(".") if best else ""
        co = lead["company"]
        if p["step"] == 1:
            return {"subject": f"Quick question on inventory planning at {co}", "evidence_ids": ids, "signal_used": fact,
                    "body": f"{hi}\n\nI noticed: {fact}. Teams in that spot often plan reorders in spreadsheets, which is where stockouts and overstock creep in.\n\n"
                            "Demand Planner X is a Shopify app that forecasts demand per SKU and recommends what to reorder and when. Worth a short look at how it would run on your own data?"}
        if p["step"] == 2:
            return {"subject": f"Re: Quick question on inventory planning at {co}", "evidence_ids": ids, "signal_used": fact,
                    "body": f"{hi}\n\nFollowing up on my note about {fact.lower()}. If reorder planning is on your plate, I can show how DPX would handle it for {co}. Open to a quick look?"}
        if p["step"] == 3:
            return {"subject": "", "evidence_ids": ids, "signal_used": fact,
                    "body": f"{hi} saw {fact.lower()}. I build a Shopify demand-planning app (DPX) and would value your take. Happy to connect."}
        return {"subject": f"Should I close the loop, {first or co}?", "evidence_ids": ids, "signal_used": fact,
                "body": f"{hi}\n\nI'll assume inventory planning isn't a priority right now and stop reaching out. If that changes, DPX forecasts demand per SKU and recommends reorders. Just reply and I'll pick it back up."}

    llm.register("draft_touch", draft)
