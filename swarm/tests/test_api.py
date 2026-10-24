import pytest
from fastapi.testclient import TestClient

from swarm.api import create_app
from swarm.config import Config
from swarm.context import build_ctx
from swarm.llm import FakeLLM
from swarm.memory import Memory

H = {"Authorization": "Bearer secret"}


@pytest.fixture()
def client():
    ctx = build_ctx(cfg=Config(db_path=":memory:"), mem=Memory(":memory:"), llm=FakeLLM())
    return TestClient(create_app(ctx, token="secret")), ctx


def test_refuses_to_start_without_token():
    with pytest.raises(RuntimeError):
        create_app(token="")


def test_requires_bearer_token(client):
    c, _ = client
    assert c.get("/stats").status_code == 401
    assert c.get("/stats", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert c.get("/stats", headers=H).status_code == 200


def test_run_review_approve_flow(client):
    c, ctx = client
    r = c.post("/run", headers=H, json={"limit": 50}).json()
    assert r["counts"]["passed"] == 8
    q = c.get("/drafts", headers=H).json()
    assert len(q) == 5 and q[0]["lead"]["company"]
    d = c.get(f"/drafts/{q[0]['id']}", headers=H).json()
    assert d["evidence"] and "unsubscribe" in d["body"].lower() and d["dry_run"] is True
    assert ctx.mem.sends_today() == 0
    a = c.post(f"/drafts/{q[0]['id']}/approve", headers=H, json={"body": d["body"].split("\n\n--\n")[0] + "\nEdited."}).json()
    assert a["lead_status"] == "contacted" and a["draft"]["status"] == "sent"
    assert "Edited." in c.get(f"/drafts/{q[0]['id']}", headers=H).json()["body"]
    # double-approve is a conflict, not a second send
    assert c.post(f"/drafts/{q[0]['id']}/approve", headers=H, json={}).status_code == 409
    assert ctx.mem.sends_today() == 1


def test_reject_and_not_found(client):
    c, _ = client
    c.post("/run", headers=H, json={})
    did = c.get("/drafts", headers=H).json()[0]["id"]
    assert c.post(f"/drafts/{did}/reject", headers=H).json()["draft"]["status"] == "rejected"
    assert c.get("/drafts/9999", headers=H).status_code == 404
    assert c.post("/drafts/9999/approve", headers=H, json={}).status_code == 404


def test_reply_brief_and_tick(client):
    c, _ = client
    c.post("/run", headers=H, json={})
    r = c.post("/leads/northwindpet.example/reply", headers=H, json={"text": "how much does it cost?"}).json()
    assert r["action"] == "reply_drafted"
    assert "Northwind" in c.get("/leads/northwindpet.example/brief", headers=H).json()["brief"]
    assert c.post("/tick", headers=H, json={"days": 5}).json() == {"started": []}
    assert c.post("/leads/nope.example/reply", headers=H, json={"text": "x"}).status_code == 404


def test_edit_cannot_strip_unsubscribe_footer(client):
    c, ctx = client
    c.post("/run", headers=H, json={})
    did = c.get("/drafts", headers=H).json()[0]["id"]
    c.post(f"/drafts/{did}/approve", headers=H, json={"body": "Totally custom note, no footer."})
    body = ctx.mem.get_draft(did).body
    assert body.startswith("Totally custom note") and 'Reply "unsubscribe"' in body
