"""Shared long-term memory + event bus (SQLite). recall(lead) is injected into every agent."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

from .models import Draft, Evidence, Lead, Score

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads(id TEXT PRIMARY KEY, domain TEXT UNIQUE, status TEXT, data TEXT, updated REAL);
CREATE TABLE IF NOT EXISTS evidence(id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id TEXT, claim TEXT, url TEXT, quote TEXT, kind TEXT);
CREATE TABLE IF NOT EXISTS scores(lead_id TEXT PRIMARY KEY, data TEXT);
CREATE TABLE IF NOT EXISTS drafts(id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id TEXT, thread_id TEXT, kind TEXT, step INTEGER,
  channel TEXT, subject TEXT, body TEXT, evidence_ids TEXT, status TEXT, created REAL, decided REAL);
CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY AUTOINCREMENT, draft_id INTEGER, lead_id TEXT, provider TEXT, dry_run INTEGER, sent_at REAL);
CREATE TABLE IF NOT EXISTS replies(id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id TEXT, body TEXT, label TEXT, action TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS suppression(email TEXT PRIMARY KEY, reason TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, run_id TEXT, lead_id TEXT, agent TEXT, kind TEXT, data TEXT);
"""


class Memory:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def _x(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    # ---- events -------------------------------------------------------
    def event(self, run_id: str, lead_id: Optional[str], agent: str, kind: str, data: Any = None) -> None:
        self._x("INSERT INTO events(ts,run_id,lead_id,agent,kind,data) VALUES(?,?,?,?,?,?)",
                (time.time(), run_id, lead_id, agent, kind, json.dumps(data, default=str)))

    def trace(self, lead_id: str) -> list[dict]:
        rows = self._x("SELECT * FROM events WHERE lead_id=? ORDER BY id", (lead_id,)).fetchall()
        return [dict(r) for r in rows]

    # ---- leads --------------------------------------------------------
    def add_lead(self, lead: Lead) -> bool:
        """Returns False if this domain was already seen (never a stranger twice)."""
        cur = self._x("INSERT OR IGNORE INTO leads(id,domain,status,data,updated) VALUES(?,?,?,?,?)",
                      (lead.id, lead.domain.lower(), "discovered", lead.model_dump_json(), time.time()))
        return cur.rowcount == 1

    def get_lead(self, lead_id: str) -> Lead:
        r = self._x("SELECT data FROM leads WHERE id=?", (lead_id,)).fetchone()
        if not r:
            raise KeyError(lead_id)
        return Lead.model_validate_json(r["data"])

    def find_lead(self, key: str) -> Optional[Lead]:
        r = self._x("SELECT data FROM leads WHERE id=? OR domain=?", (key, key.lower())).fetchone()
        return Lead.model_validate_json(r["data"]) if r else None

    def set_status(self, lead_id: str, status: str) -> None:
        self._x("UPDATE leads SET status=?, updated=? WHERE id=?", (status, time.time(), lead_id))

    def status(self, lead_id: str) -> str:
        r = self._x("SELECT status FROM leads WHERE id=?", (lead_id,)).fetchone()
        return r["status"] if r else ""

    def leads_by_status(self, status: str) -> list[Lead]:
        rows = self._x("SELECT data FROM leads WHERE status=?", (status,)).fetchall()
        return [Lead.model_validate_json(r["data"]) for r in rows]

    # ---- evidence / scores -------------------------------------------
    def add_evidence(self, ev: Evidence) -> int:
        cur = self._x("INSERT INTO evidence(lead_id,claim,url,quote,kind) VALUES(?,?,?,?,?)",
                      (ev.lead_id, ev.claim, ev.url, ev.quote, ev.kind))
        return int(cur.lastrowid)

    def evidence(self, lead_id: str) -> list[Evidence]:
        rows = self._x("SELECT * FROM evidence WHERE lead_id=? ORDER BY id", (lead_id,)).fetchall()
        return [Evidence(**dict(r)) for r in rows]

    def save_score(self, s: Score) -> None:
        self._x("INSERT OR REPLACE INTO scores(lead_id,data) VALUES(?,?)", (s.lead_id, s.model_dump_json()))

    def get_score(self, lead_id: str) -> Optional[Score]:
        r = self._x("SELECT data FROM scores WHERE lead_id=?", (lead_id,)).fetchone()
        return Score.model_validate_json(r["data"]) if r else None

    # ---- drafts / sends ----------------------------------------------
    def add_draft(self, d: Draft) -> int:
        cur = self._x(
            "INSERT INTO drafts(lead_id,thread_id,kind,step,channel,subject,body,evidence_ids,status,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (d.lead_id, d.thread_id, d.kind, d.step, d.channel, d.subject, d.body, json.dumps(d.evidence_ids), d.status, time.time()))
        return int(cur.lastrowid)

    def get_draft(self, draft_id: int) -> Draft:
        r = self._x("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
        if not r:
            raise KeyError(draft_id)
        d = dict(r)
        return Draft(id=d["id"], lead_id=d["lead_id"], thread_id=d["thread_id"], kind=d["kind"], step=d["step"],
                     channel=d["channel"], subject=d["subject"], body=d["body"],
                     evidence_ids=json.loads(d["evidence_ids"]), status=d["status"])

    def drafts(self, status: Optional[str] = None, lead_id: Optional[str] = None) -> list[Draft]:
        q, a = "SELECT id FROM drafts WHERE 1=1", []
        if status:
            q += " AND status=?"; a.append(status)
        if lead_id:
            q += " AND lead_id=?"; a.append(lead_id)
        return [self.get_draft(r["id"]) for r in self._x(q + " ORDER BY id", tuple(a)).fetchall()]

    def update_draft(self, draft_id: int, status: Optional[str] = None, body: Optional[str] = None) -> None:
        if body is not None:
            self._x("UPDATE drafts SET body=? WHERE id=?", (body, draft_id))
        if status is not None:
            self._x("UPDATE drafts SET status=?, decided=? WHERE id=?", (status, time.time(), draft_id))

    def record_send(self, draft_id: int, lead_id: str, provider: str, dry_run: bool) -> None:
        self._x("INSERT INTO outbox(draft_id,lead_id,provider,dry_run,sent_at) VALUES(?,?,?,?,?)",
                (draft_id, lead_id, provider, int(dry_run), time.time()))

    def sends_today(self) -> int:
        cutoff = time.time() - 86400
        return self._x("SELECT COUNT(*) c FROM outbox WHERE sent_at>?", (cutoff,)).fetchone()["c"]

    def last_send(self, lead_id: str) -> Optional[dict]:
        r = self._x("SELECT o.sent_at, d.step, d.kind FROM outbox o JOIN drafts d ON d.id=o.draft_id "
                    "WHERE o.lead_id=? AND d.kind='touch' ORDER BY o.id DESC LIMIT 1", (lead_id,)).fetchone()
        return dict(r) if r else None

    # ---- replies / suppression ---------------------------------------
    def add_reply(self, lead_id: str, body: str, label: str, action: str) -> None:
        self._x("INSERT INTO replies(lead_id,body,label,action,ts) VALUES(?,?,?,?,?)", (lead_id, body, label, action, time.time()))

    def replies(self, lead_id: str) -> list[dict]:
        return [dict(r) for r in self._x("SELECT * FROM replies WHERE lead_id=? ORDER BY id", (lead_id,)).fetchall()]

    def suppress(self, email: str, reason: str) -> None:
        self._x("INSERT OR REPLACE INTO suppression(email,reason,ts) VALUES(?,?,?)", (email.lower(), reason, time.time()))

    def is_suppressed(self, email: str) -> bool:
        return self._x("SELECT 1 FROM suppression WHERE email=?", (email.lower(),)).fetchone() is not None

    # ---- recall -------------------------------------------------------
    def recall(self, lead_id: str) -> dict:
        """Everything known about a lead. Injected into follow-ups, reply handling, meeting briefs."""
        return {
            "lead": self.get_lead(lead_id).model_dump(),
            "status": self.status(lead_id),
            "evidence": [e.model_dump() for e in self.evidence(lead_id)],
            "score": (self.get_score(lead_id).model_dump() if self.get_score(lead_id) else None),
            "drafts": [{"id": d.id, "step": d.step, "kind": d.kind, "status": d.status, "subject": d.subject, "body": d.body}
                       for d in self.drafts(lead_id=lead_id)],
            "replies": self.replies(lead_id),
        }

    def funnel(self) -> dict[str, int]:
        rows = self._x("SELECT status, COUNT(*) c FROM leads GROUP BY status").fetchall()
        return {r["status"]: r["c"] for r in rows}
