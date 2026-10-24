"""HTTP API behind the Next.js approval UI. The UI is the only intended client.
All routes require a bearer token; the server refuses to start without one."""
from __future__ import annotations

import hmac
import os
import threading
import time
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from .agents import discovery, inbox, meeting
from .context import Ctx, build_ctx
from .graph import build_graph, decide, run_lead, tick


class Decision(BaseModel):
    body: Optional[str] = None


class RunReq(BaseModel):
    limit: int = 50


class TickReq(BaseModel):
    days: float = 0


class ReplyReq(BaseModel):
    text: str


def create_app(ctx: Optional[Ctx] = None, token: Optional[str] = None) -> FastAPI:
    token = token if token is not None else os.environ.get("SWARM_API_TOKEN", "")
    if not token:
        raise RuntimeError("SWARM_API_TOKEN is not set; refusing to start an unauthenticated approval API")
    ctx = ctx or build_ctx(run_id="api")
    graph = build_graph(ctx)
    write_lock = threading.Lock()  # one mutation at a time: graph resume + sqlite writes

    def auth(authorization: str = Header(default="")) -> None:
        supplied = authorization.removeprefix("Bearer ").strip()
        if not hmac.compare_digest(supplied.encode(), token.encode()):
            raise HTTPException(401, "invalid token")

    app = FastAPI(title="DPX swarm API", dependencies=[Depends(auth)])

    def draft_view(d, full: bool = False) -> dict:
        lead = ctx.mem.get_lead(d.lead_id)
        sc = ctx.mem.get_score(d.lead_id)
        out = {"id": d.id, "kind": d.kind, "step": d.step, "channel": d.channel, "subject": d.subject, "status": d.status,
               "lead": {"id": lead.id, "company": lead.company, "domain": lead.domain, "contact_name": lead.contact_name,
                        "title": lead.title, "email": lead.email}, "score": sc.composite if sc else None}
        if full:
            ev = {e.id: e for e in ctx.mem.evidence(d.lead_id)}
            out.update(body=d.body, evidence=[ev[i].model_dump() for i in d.evidence_ids if i in ev],
                       score_detail=sc.model_dump() if sc else None,
                       replies=ctx.mem.replies(d.lead_id), dry_run=ctx.cfg.dry_run)
        return out

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "dry_run": ctx.cfg.dry_run, "llm": type(ctx.llm).__name__, "daily_cap": ctx.cfg.daily_send_cap,
                "sent_24h": ctx.mem.sends_today()}

    @app.get("/stats")
    def stats() -> dict:
        return {"funnel": ctx.mem.funnel(), "pending": len(ctx.mem.drafts(status="pending")),
                "sent_24h": ctx.mem.sends_today(), "daily_cap": ctx.cfg.daily_send_cap, "dry_run": ctx.cfg.dry_run}

    @app.get("/drafts")
    def list_drafts(status: str = "pending") -> list[dict]:
        return [draft_view(d) for d in ctx.mem.drafts(status=status)]

    @app.get("/drafts/{draft_id}")
    def get_draft(draft_id: int) -> dict:
        try:
            return draft_view(ctx.mem.get_draft(draft_id), full=True)
        except KeyError:
            raise HTTPException(404, "draft not found")

    def _decide(draft_id: int, action: str, body: Optional[str]) -> dict:
        with write_lock:
            try:
                status = decide(ctx, graph, draft_id, action, body)
            except KeyError:
                raise HTTPException(404, "draft not found")
            except ValueError as e:
                raise HTTPException(409, str(e))
        return {"lead_status": status, "draft": draft_view(ctx.mem.get_draft(draft_id))}

    @app.post("/drafts/{draft_id}/approve")
    def approve(draft_id: int, d: Decision = Decision()) -> dict:
        return _decide(draft_id, "approve", d.body)

    @app.post("/drafts/{draft_id}/reject")
    def reject(draft_id: int) -> dict:
        return _decide(draft_id, "reject", None)

    @app.post("/run")
    def run(r: RunReq = RunReq()) -> dict:
        with write_lock:
            found = discovery.run(ctx, r.limit)
            results = {lid: run_lead(ctx, graph, lid) for lid in found["passed"]}
        return {"counts": {k: len(v) for k, v in found.items()}, "results": results}

    @app.post("/tick")
    def do_tick(r: TickReq = TickReq()) -> dict:
        with write_lock:
            return {"started": tick(ctx, graph, time.time() + r.days * 86400)}

    @app.post("/leads/{key}/reply")
    def reply(key: str, r: ReplyReq) -> dict:
        lead = ctx.mem.find_lead(key)
        if not lead:
            raise HTTPException(404, "lead not found")
        with write_lock:
            return inbox.handle(ctx, lead.id, r.text)

    @app.get("/leads/{key}/brief")
    def brief(key: str) -> dict:
        lead = ctx.mem.find_lead(key)
        if not lead:
            raise HTTPException(404, "lead not found")
        return {"brief": meeting.brief(ctx, lead.id)}

    return app


def main() -> None:
    import uvicorn

    uvicorn.run(create_app(), host=os.environ.get("SWARM_API_HOST", "127.0.0.1"), port=int(os.environ.get("SWARM_API_PORT", "8000")))


if __name__ == "__main__":
    main()
