"""Typed contracts passed between agents. Every handoff is one of these."""
from __future__ import annotations

import hashlib
from typing import Optional

from pydantic import BaseModel, Field


class ICP(BaseModel):
    """Queryable spec. Downstream agents consume this; it is not a PDF."""

    name: str
    product: str
    platforms: list[str]
    min_employees: int
    max_employees: int
    min_gmv: int  # annual USD
    max_gmv: int
    target_titles: list[str]  # lowercase substrings, ordered by priority
    pain_signals: list[str]  # lowercase keywords that indicate inventory pain
    tech_signals: list[str]  # lowercase keywords that indicate compatible stack
    disqualifiers: list[str]  # lowercase keywords: any hit = hard reject


class Lead(BaseModel):
    id: str
    company: str
    domain: str
    contact_name: str = ""
    title: str = ""
    email: str = ""
    linkedin: str = ""
    employees: Optional[int] = None
    gmv: Optional[int] = None
    platform: str = ""
    snippet: str = ""  # cheap text used for pre-filtering
    raw: dict = Field(default_factory=dict)

    @staticmethod
    def make_id(domain: str) -> str:
        return hashlib.sha1(domain.strip().lower().encode()).hexdigest()[:12]


class Evidence(BaseModel):
    """One claim, one source, one quote. The outreach agent may only use these."""

    id: int = 0
    lead_id: str
    claim: str
    url: str
    quote: str
    kind: str = "general"  # funding | hiring | tech | pain | news | general


class Score(BaseModel):
    lead_id: str
    icp_fit: float  # each criterion 0-5
    tech_fit: float
    intent: float
    authority: float
    urgency: float
    composite: float  # 0-100
    passed: bool
    reasons: list[str] = Field(default_factory=list)
    cited_evidence: list[int] = Field(default_factory=list)


class Draft(BaseModel):
    id: int = 0
    lead_id: str
    thread_id: str
    kind: str  # touch | reply
    step: int
    channel: str  # email | linkedin
    subject: str = ""
    body: str
    evidence_ids: list[int] = Field(default_factory=list)
    status: str = "pending"  # pending | approved | rejected | sent
