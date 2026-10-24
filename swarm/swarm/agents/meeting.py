"""Pre-call brief for the human AE, built purely from shared memory (no LLM, no hallucination surface)."""
from __future__ import annotations

from ..context import Ctx


def brief(ctx: Ctx, lead_id: str) -> str:
    m = ctx.mem.recall(lead_id)
    lead, score = m["lead"], m["score"]
    pain = [e for e in m["evidence"] if e["kind"] in ("pain", "hiring")] or m["evidence"]
    lines = [f"# Call brief: {lead['company']} ({lead['domain']})",
             f"Contact: {lead['contact_name'] or 'unknown'}, {lead['title'] or 'unknown title'}  <{lead['email']}>",
             f"Status: {m['status']}  |  Fit score: {score['composite'] if score else 'n/a'}", "",
             "## Problem (from evidence)"]
    lines += [f"- {e['claim']}  [{e['url']}] \"{e['quote']}\"" for e in pain] or ["- none recorded"]
    lines += ["", "## Matched service", "- Demand Planner X: per-SKU demand forecasts + reorder recommendations for Shopify", "", "## Conversation so far"]
    for d in m["drafts"]:
        if d["status"] == "sent":
            lines.append(f"- Sent {d['kind']} #{d['step']}: {d['subject'] or '(LinkedIn)'}")
    for r in m["replies"]:
        lines.append(f"- Reply [{r['label']}]: {r['body']}")
    objections = [r for r in m["replies"] if "objection" in r["label"] or r["label"] == "question"]
    lines += ["", "## Objections / questions raised"] + ([f"- {r['label']}: {r['body']}" for r in objections] or ["- none yet"])
    lines += ["", "## Talking points", "- Open with their own signal above, then ask how reorders are planned today",
              "- Offer to run DPX on their data rather than quoting results (no verified metrics in KB)",
              "- Pricing: not in KB; handle live"]
    return "\n".join(lines)
