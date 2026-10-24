"""Stage 3a: evidence dossier. Every claim stored with URL + quote."""
from __future__ import annotations

from ..context import Ctx


def run(ctx: Ctx, lead_id: str) -> int:
    lead = ctx.mem.get_lead(lead_id)
    if ctx.mem.evidence(lead_id):  # idempotent on resume/retry
        return len(ctx.mem.evidence(lead_id))
    n = 0
    for ev in ctx.researcher.research(lead):
        if not (ev.claim and ev.url and ev.quote):  # evidence must be fully sourced
            continue
        ctx.mem.add_evidence(ev); n += 1
    ctx.mem.set_status(lead_id, "researched" if n else "no_evidence")
    ctx.log(lead_id, "research", "dossier", {"evidence": n})
    return n
