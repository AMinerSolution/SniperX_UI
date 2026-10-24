"""LangGraph per-lead relay: research -> qualify -> draft -> [HUMAN APPROVAL interrupt] -> send.
Discovery + prefilter run as a batch before this graph. State is checkpointed, so approvals can arrive hours later."""
from __future__ import annotations

import sqlite3
import time
from typing import Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .agents import outreach, qualifier, research
from .compliance import ready_to_send
from .context import Ctx


class S(TypedDict, total=False):
    lead_id: str
    step: int
    draft_id: int
    outcome: str  # continue | stop


def build_graph(ctx: Ctx):
    mem = ctx.mem

    def route(s: S) -> str:
        return "research" if s["step"] == 1 else "draft"

    def research_n(s: S) -> S:
        n = research.run(ctx, s["lead_id"])
        return {"outcome": "continue" if n else "stop"}

    def qualify_n(s: S) -> S:
        return {"outcome": "continue" if qualifier.run(ctx, s["lead_id"]).passed else "stop"}

    def draft_n(s: S) -> S:
        lid, lead = s["lead_id"], mem.get_lead(s["lead_id"])
        if lead.email and mem.is_suppressed(lead.email):
            mem.set_status(lid, "unsubscribed"); return {"outcome": "stop"}
        if s["step"] > 1 and mem.status(lid) not in ("contacted",):
            ctx.log(lid, "graph", "skip_followup", {"status": mem.status(lid)}); return {"outcome": "stop"}
        try:
            d = outreach.run(ctx, lid, s["step"])
        except outreach.DraftRejected as e:
            mem.set_status(lid, "draft_failed"); ctx.log(lid, "outreach", "draft_failed", str(e)); return {"outcome": "stop"}
        mem.set_status(lid, "pending_approval")
        ctx.log(lid, "outreach", "draft_queued", {"draft_id": d.id, "step": d.step})
        return {"draft_id": d.id, "outcome": "continue"}

    def approval_n(s: S) -> S:
        d = mem.get_draft(s["draft_id"])
        # Node re-runs from the top on resume: keep everything above this line side-effect free.
        decision = interrupt({"draft_id": d.id, "lead_id": d.lead_id, "step": d.step, "subject": d.subject, "body": d.body})
        if decision.get("action") == "approve":
            mem.update_draft(d.id, status="approved", body=decision.get("body"))
            ctx.log(d.lead_id, "human", "approved", {"draft_id": d.id, "edited": decision.get("body") is not None})
            return {"outcome": "continue"}
        mem.update_draft(d.id, status="rejected")
        mem.set_status(d.lead_id, "contacted" if d.step > 1 else "draft_rejected")
        ctx.log(d.lead_id, "human", "rejected", {"draft_id": d.id})
        return {"outcome": "stop"}

    def send_n(s: S) -> S:
        d = mem.get_draft(s["draft_id"]); lead = mem.get_lead(d.lead_id)
        problems = [] if ctx.cfg.dry_run else ready_to_send(ctx.cfg)
        if lead.email and mem.is_suppressed(lead.email):
            problems.append("recipient suppressed")
        if mem.sends_today() >= ctx.cfg.daily_send_cap:
            problems.append(f"daily send cap {ctx.cfg.daily_send_cap} reached")
        if problems:  # stays approved-but-unsent; retry via `swarm send-approved`
            ctx.log(d.lead_id, "sender", "blocked", problems); mem.set_status(d.lead_id, "send_blocked"); return {"outcome": "stop"}
        msg_id = ctx.sender.send(d, lead)
        mem.record_send(d.id, d.lead_id, ctx.sender.name, ctx.cfg.dry_run)
        mem.update_draft(d.id, status="sent")
        last = d.step >= outreach.SEQUENCE[-1][0]
        mem.set_status(d.lead_id, "sequence_complete" if last else "contacted")
        ctx.log(d.lead_id, "sender", "sent", {"draft_id": d.id, "provider": ctx.sender.name, "dry_run": ctx.cfg.dry_run, "msg_id": msg_id})
        return {"outcome": "continue"}

    go = lambda nxt: (lambda s: nxt if s.get("outcome") == "continue" else END)  # noqa: E731
    g = StateGraph(S)
    for name, fn in [("research", research_n), ("qualify", qualify_n), ("draft", draft_n), ("approval", approval_n), ("send", send_n)]:
        g.add_node(name, fn)
    g.add_conditional_edges(START, route, {"research": "research", "draft": "draft"})
    g.add_conditional_edges("research", go("qualify"), {"qualify": "qualify", END: END})
    g.add_conditional_edges("qualify", go("draft"), {"draft": "draft", END: END})
    g.add_conditional_edges("draft", go("approval"), {"approval": "approval", END: END})
    g.add_conditional_edges("approval", go("send"), {"send": "send", END: END})
    g.add_edge("send", END)

    if ctx.cfg.db_path == ":memory:":
        saver = MemorySaver()
    else:
        saver = SqliteSaver(sqlite3.connect(ctx.cfg.db_path + ".ckpt", check_same_thread=False))
    return g.compile(checkpointer=saver)


def run_lead(ctx: Ctx, graph, lead_id: str, step: int = 1) -> str:
    cfg = {"configurable": {"thread_id": f"{lead_id}:{step}"}}
    graph.invoke({"lead_id": lead_id, "step": step}, cfg)
    return ctx.mem.status(lead_id)


def decide(ctx: Ctx, graph, draft_id: int, action: str, body: Optional[str] = None) -> str:
    """Resume the paused graph with the human's decision (touches) or send directly (reply drafts)."""
    d = ctx.mem.get_draft(draft_id)
    if d.status != "pending":
        raise ValueError(f"draft {draft_id} is {d.status}, not pending")
    if d.kind == "reply":
        if action == "approve":
            if body:
                ctx.mem.update_draft(draft_id, body=body)
            lead = ctx.mem.get_lead(d.lead_id)
            if lead.email and ctx.mem.is_suppressed(lead.email):
                raise ValueError("recipient is suppressed")
            ctx.mem.update_draft(draft_id, status="approved")
            ctx.sender.send(ctx.mem.get_draft(draft_id), lead)
            ctx.mem.record_send(draft_id, d.lead_id, ctx.sender.name, ctx.cfg.dry_run)
            ctx.mem.update_draft(draft_id, status="sent")
            ctx.log(d.lead_id, "sender", "sent", {"draft_id": draft_id, "kind": "reply", "dry_run": ctx.cfg.dry_run})
        else:
            ctx.mem.update_draft(draft_id, status="rejected")
        return ctx.mem.status(d.lead_id)
    cfg = {"configurable": {"thread_id": d.thread_id}}
    graph.invoke(Command(resume={"action": action, "body": body}), cfg)
    return ctx.mem.status(d.lead_id)


def tick(ctx: Ctx, graph, now: Optional[float] = None) -> list[str]:
    """Advance follow-ups that are due (Day 4 / 7 / 12). `now` lets you simulate time passing."""
    now = now or time.time()
    started = []
    for lead in ctx.mem.leads_by_status("contacted"):
        last = ctx.mem.last_send(lead.id)
        if not last or ctx.mem.replies(lead.id):
            continue
        nxt = next((s for s in outreach.SEQUENCE if s[0] == last["step"] + 1), None)
        if nxt and last["sent_at"] + nxt[2] * 86400 <= now:
            run_lead(ctx, graph, lead.id, nxt[0]); started.append(f"{lead.id}:{nxt[0]}")
    return started
