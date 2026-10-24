"""Stage 3b: evidence-gated, multi-criteria scoring. Can and does reject."""
from __future__ import annotations

from ..context import Ctx
from ..models import Lead, Score

WEIGHTS = {"icp_fit": 0.25, "tech_fit": 0.15, "intent": 0.30, "authority": 0.15, "urgency": 0.15}


def _icp_fit(ctx: Ctx, lead: Lead) -> float:
    i = ctx.icp
    s = 0.0
    s += 2.5 if lead.employees is not None and i.min_employees <= lead.employees <= i.max_employees else (1.0 if lead.employees is None else 0)
    s += 2.5 if lead.gmv is not None and i.min_gmv <= lead.gmv <= i.max_gmv else (1.0 if lead.gmv is None else 0)
    return s


def _tech_fit(ctx: Ctx, lead: Lead, evidence) -> float:
    text = (lead.snippet + " " + " ".join(f"{e.claim} {e.quote}" for e in evidence)).lower()
    hits = {t for t in ctx.icp.tech_signals if t in text}
    score = 2.0 if "shopify" in hits else 0.0
    score += 1.5 if "shopify plus" in hits else 0.0
    score += min(1.5, 0.75 * len(hits - {"shopify", "shopify plus"}))
    return min(5.0, score)


def _authority(ctx: Ctx, lead: Lead) -> float:
    t = lead.title.lower()
    if not t:
        return 0.0
    titles = ctx.icp.target_titles
    for idx, name in enumerate(titles):
        if name in t:
            return 5.0 if idx < 8 else 4.0  # ops/supply-chain/COO first, founder/owner next
    return 1.0


def run(ctx: Ctx, lead_id: str) -> Score:
    lead = ctx.mem.get_lead(lead_id)
    evidence = ctx.mem.evidence(lead_id)
    valid_ids = {e.id for e in evidence}
    j = ctx.llm.json(
        "qualify_judgment",
        "Score buying INTENT and URGENCY (0-5 each) for an inventory-planning app, using ONLY the evidence given. "
        'Return {"intent": n, "urgency": n, "cited_evidence": [evidence ids], "reasons": [str]}. '
        "Any score above 0 must cite the evidence ids that justify it.",
        {"icp": ctx.icp.model_dump(), "evidence": [e.model_dump() for e in evidence]}, tier="mid")
    cited = [i for i in j.get("cited_evidence", []) if i in valid_ids]
    intent, urgency = float(j.get("intent", 0)), float(j.get("urgency", 0))
    reasons = list(j.get("reasons", []))
    if not cited and (intent or urgency):  # evidence gate: unsupported scores are zeroed
        intent = urgency = 0.0
        reasons.append("intent/urgency zeroed: no valid evidence cited")
    crit = {"icp_fit": _icp_fit(ctx, lead), "tech_fit": _tech_fit(ctx, lead, evidence),
            "intent": min(5, max(0, intent)), "authority": _authority(ctx, lead), "urgency": min(5, max(0, urgency))}
    composite = round(sum(WEIGHTS[k] * v / 5 for k, v in crit.items()) * 100, 1)
    passed = composite >= ctx.cfg.min_score
    margin = 5.0
    if abs(composite - ctx.cfg.min_score) < margin:  # edge case only: LLM tiebreaker
        t = ctx.llm.json("qualify_tiebreak", 'Borderline lead. Return {"pass": bool, "reason": str}.',
                         {"composite": composite, "criteria": crit, "evidence": [e.model_dump() for e in evidence]}, tier="mid")
        passed = bool(t.get("pass")) and bool(cited)
        reasons.append(f"tiebreak: {t.get('reason', '')}")
    s = Score(lead_id=lead_id, composite=composite, passed=passed, reasons=reasons, cited_evidence=cited, **crit)
    ctx.mem.save_score(s)
    ctx.mem.set_status(lead_id, "qualified" if passed else "rejected")
    ctx.log(lead_id, "qualifier", "score", s.model_dump())
    return s


def register_fake(llm) -> None:
    def judgment(p: dict) -> dict:
        pain = p["icp"]["pain_signals"]
        hits, cited, urgency = set(), [], 0.0
        for e in p["evidence"]:
            text = f"{e['claim']} {e['quote']}".lower()
            m = {s for s in pain if s in text}
            if m:
                hits |= m; cited.append(e["id"])
            if e["kind"] == "hiring":
                urgency += 2.5
            if any(w in text for w in ("sold out", "backorder", "stockout", "overstock", "clearance")):
                urgency += 2.5
        return {"intent": min(5, 2 * len(hits)), "urgency": min(5, urgency), "cited_evidence": cited,
                "reasons": [f"pain signals: {sorted(hits)}"] if hits else ["no pain signals in evidence"]}

    llm.register("qualify_judgment", judgment)
    llm.register("qualify_tiebreak", lambda p: {"pass": p["criteria"]["intent"] >= 3, "reason": "fake: pass if intent>=3"})
