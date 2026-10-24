"""Stage 2: discover, then cheap filtering BEFORE any research tokens are spent."""
from __future__ import annotations

from ..context import Ctx
from ..models import ICP, Lead


def prefilter(icp: ICP, lead: Lead) -> tuple[str, str]:
    """Deterministic rules first. Returns (pass|fail|unsure, reason)."""
    text = f"{lead.company} {lead.snippet}".lower()
    for d in icp.disqualifiers:
        if d in text:
            return "fail", f"disqualifier '{d}'"
    if lead.platform and lead.platform not in icp.platforms:
        return "fail", f"platform '{lead.platform}' not in ICP"
    if lead.employees is not None and not icp.min_employees <= lead.employees <= icp.max_employees:
        return "fail", f"employees {lead.employees} outside {icp.min_employees}-{icp.max_employees}"
    if lead.gmv is not None and not icp.min_gmv <= lead.gmv <= icp.max_gmv:
        return "fail", f"gmv {lead.gmv} outside {icp.min_gmv}-{icp.max_gmv}"
    if not lead.platform or lead.employees is None or lead.gmv is None:
        return "unsure", "missing size/platform data"
    return "pass", "within ICP bounds"


def run(ctx: Ctx, limit: int = 50) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"passed": [], "filtered_out": [], "duplicate": [], "suppressed": []}
    for lead in ctx.discovery.discover(ctx.icp, limit):
        if lead.email and ctx.mem.is_suppressed(lead.email):
            out["suppressed"].append(lead.id); continue
        if not ctx.mem.add_lead(lead):  # never a stranger twice
            out["duplicate"].append(lead.id); continue
        verdict, reason = prefilter(ctx.icp, lead)
        if verdict == "unsure":
            r = ctx.llm.json("prefilter_edge", "Decide if this company plausibly fits the ICP from the snippet alone. "
                             'Return {"pass": bool, "reason": str}.',
                             {"icp": ctx.icp.model_dump(), "lead": lead.model_dump(exclude={"raw"})}, tier="cheap")
            verdict, reason = ("pass" if r.get("pass") else "fail"), "llm: " + str(r.get("reason", ""))
        ctx.log(lead.id, "discovery", "prefilter", {"verdict": verdict, "reason": reason})
        if verdict == "pass":
            ctx.mem.set_status(lead.id, "filtered"); out["passed"].append(lead.id)
        else:
            ctx.mem.set_status(lead.id, "filtered_out"); out["filtered_out"].append(lead.id)
    return out


def register_fake(llm) -> None:
    def prefilter_edge(p: dict) -> dict:
        text = p["lead"].get("snippet", "").lower()
        hit = [s for s in p["icp"]["tech_signals"] if s in text]
        return {"pass": bool(hit), "reason": f"snippet mentions {hit}" if hit else "no ICP signal in snippet"}

    llm.register("prefilter_edge", prefilter_edge)
