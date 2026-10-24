import time

import pytest

from swarm.agents import discovery, inbox, meeting, outreach, qualifier
from swarm.config import Config
from swarm.context import build_ctx
from swarm.graph import build_graph, decide, run_lead, tick
from swarm.llm import FakeLLM
from swarm.memory import Memory
from swarm.models import Evidence, Lead


def make(**cfg_over):
    cfg = Config(db_path=":memory:", **cfg_over)
    ctx = build_ctx(cfg=cfg, mem=Memory(":memory:"), llm=FakeLLM())
    return ctx, build_graph(ctx)


def lead_id(ctx, domain):
    return ctx.mem.find_lead(domain).id


def test_prefilter_rules_and_dedupe():
    ctx, _ = make()
    out = discovery.run(ctx)
    assert len(out["passed"]) == 8 and len(out["filtered_out"]) == 4
    for d in ("dropwavegadgets.example", "pixelcoagency.example", "megamartwholesale.example", "tinycandle.example"):
        assert ctx.mem.status(lead_id(ctx, d)) == "filtered_out"
    assert len(discovery.run(ctx)["duplicate"]) == 12  # never a stranger twice


def test_nothing_sent_before_approval_then_dry_run_send():
    ctx, g = make()
    out = discovery.run(ctx)
    lid = lead_id(ctx, "ridgelineoutdoor.example")
    assert run_lead(ctx, g, lid) == "pending_approval"
    assert ctx.mem.sends_today() == 0
    (d,) = ctx.mem.drafts(status="pending")
    assert decide(ctx, g, d.id, "approve") == "contacted"
    assert ctx.mem.sends_today() == 1 and ctx.mem.get_draft(d.id).status == "sent"


def test_weak_lead_is_rejected_by_qualifier():
    ctx, g = make()
    discovery.run(ctx)
    assert run_lead(ctx, g, lead_id(ctx, "brightleaftea.example")) == "rejected"  # no pain evidence
    assert not ctx.mem.drafts()


def test_evidence_gate_zeroes_uncited_scores():
    ctx, g = make()
    discovery.run(ctx)
    ctx.llm.register("qualify_judgment", lambda p: {"intent": 5, "urgency": 5, "cited_evidence": [999], "reasons": []})
    lid = lead_id(ctx, "brightleaftea.example")
    from swarm.agents import research
    research.run(ctx, lid)
    s = qualifier.run(ctx, lid)
    assert s.intent == 0 and s.urgency == 0 and not s.passed


def test_ungrounded_draft_is_blocked():
    ctx, g = make()
    discovery.run(ctx)
    ctx.llm.register("draft_touch", lambda p: {"subject": "Hi", "body": "We cut stockouts by 37% for brands like yours.", "evidence_ids": [1], "signal_used": "x"})
    assert run_lead(ctx, g, lead_id(ctx, "ridgelineoutdoor.example")) == "draft_failed"
    assert not ctx.mem.drafts()


def test_draft_validator_requires_valid_evidence():
    ev = [Evidence(id=1, lead_id="x", claim="Sold out tents", url="u", quote="sold out")]
    assert outreach.validate("Hello there", "s", [], ev, "", 1, "email")
    assert outreach.validate("Hello there", "s", [7], ev, "", 1, "email")
    assert not outreach.validate("Hello there", "s", [1], ev, "", 1, "email")


def test_unsubscribe_suppresses_and_cancels_pending():
    ctx, g = make()
    discovery.run(ctx)
    lid = lead_id(ctx, "ridgelineoutdoor.example")
    run_lead(ctx, g, lid)
    decide(ctx, g, ctx.mem.drafts(status="pending")[0].id, "approve")
    tick(ctx, g, time.time() + 4 * 86400)
    assert len(ctx.mem.drafts(status="pending")) == 1  # day-4 follow-up queued
    assert inbox.handle(ctx, lid, "please unsubscribe me")["action"] == "suppressed"
    assert not ctx.mem.drafts(status="pending")
    assert ctx.mem.is_suppressed("dana@ridgelineoutdoor.example")
    assert ctx.mem.status(lid) == "unsubscribed"


def test_followup_timing_and_reply_stops_sequence():
    ctx, g = make()
    discovery.run(ctx)
    lid = lead_id(ctx, "northwindpet.example")
    run_lead(ctx, g, lid)
    decide(ctx, g, ctx.mem.drafts(status="pending")[0].id, "approve")
    assert tick(ctx, g, time.time() + 1 * 86400) == []          # too early
    assert tick(ctx, g, time.time() + 4 * 86400) == [f"{lid}:2"]
    inbox.handle(ctx, lid, "sounds good, let's talk")
    assert tick(ctx, g, time.time() + 30 * 86400) == []           # replied -> sequence stops


def test_full_sequence_completes():
    ctx, g = make()
    discovery.run(ctx)
    lid = lead_id(ctx, "northwindpet.example")
    run_lead(ctx, g, lid)
    t = time.time()
    for day in (0, 4, 8, 14):
        if day:
            tick(ctx, g, t + day * 86400)
        decide(ctx, g, ctx.mem.drafts(status="pending")[0].id, "approve")
    assert ctx.mem.status(lid) == "sequence_complete"
    assert [d.channel for d in ctx.mem.drafts(lead_id=lid)] == ["email", "email", "linkedin", "email"]


def test_unknown_question_says_confirm_on_call():
    ctx, g = make()
    discovery.run(ctx)
    lid = lead_id(ctx, "northwindpet.example")
    r = inbox.handle(ctx, lid, "Does it support SOC 2 and what is the roadmap?")
    body = ctx.mem.get_draft(r["draft_id"]).body
    assert "confirm that on a call" in body


def test_pricing_reply_does_not_invent_price():
    ctx, g = make()
    discovery.run(ctx)
    r = inbox.handle(ctx, lead_id(ctx, "northwindpet.example"), "how much does it cost?")
    body = ctx.mem.get_draft(r["draft_id"]).body
    assert "$" not in body.split("--")[0]


def test_send_cap_blocks():
    ctx, g = make(daily_send_cap=1)
    discovery.run(ctx)
    ids = [lead_id(ctx, d) for d in ("ridgelineoutdoor.example", "northwindpet.example")]
    for i in ids:
        run_lead(ctx, g, i)
    for d in ctx.mem.drafts(status="pending"):
        decide(ctx, g, d.id, "approve")
    assert ctx.mem.sends_today() == 1
    assert ctx.mem.status(ids[1]) == "send_blocked"


def test_live_send_requires_compliance_fields():
    ctx, g = make(dry_run=False)
    discovery.run(ctx)
    lid = lead_id(ctx, "ridgelineoutdoor.example")
    run_lead(ctx, g, lid)
    assert decide(ctx, g, ctx.mem.drafts(status="pending")[0].id, "approve") == "send_blocked"
    assert ctx.mem.sends_today() == 0


def test_brief_uses_memory():
    ctx, g = make()
    discovery.run(ctx)
    lid = lead_id(ctx, "northwindpet.example")
    run_lead(ctx, g, lid)
    inbox.handle(ctx, lid, "how does it work?")
    b = meeting.brief(ctx, lid)
    assert "warehouses" in b and "question" in b
