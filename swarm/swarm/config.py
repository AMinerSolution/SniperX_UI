"""Environment-driven config. Safe defaults: offline, dry-run."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


def _bool(v: str | None, default: bool) -> bool:
    return default if v is None or v == "" else v.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Config:
    db_path: str = ".data/swarm.db"
    llm: str = "auto"
    anthropic_key: str = ""
    model_cheap: str = "claude-haiku-5-5"
    model_mid: str = "claude-sonnet-5-5"
    model_top: str = "claude-opus-5-5"
    dry_run: bool = True
    daily_send_cap: int = 20
    min_score: float = 60.0
    sender_name: str = ""
    sender_company: str = "SupliiChain"
    sender_address: str = ""
    discovery: str = "csv"
    research: str = "fixture"
    sender: str = "dryrun"
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Config":
        e = os.environ
        return cls(
            db_path=e.get("SWARM_DB", ".data/swarm.db"),
            llm=e.get("SWARM_LLM", "auto"),
            anthropic_key=e.get("ANTHROPIC_API_KEY", ""),
            model_cheap=e.get("MODEL_CHEAP", "claude-haiku-5-5"),
            model_mid=e.get("MODEL_MID", "claude-sonnet-5-5"),
            model_top=e.get("MODEL_TOP", "claude-opus-5-5"),
            dry_run=_bool(e.get("DRY_RUN"), True),
            daily_send_cap=int(e.get("DAILY_SEND_CAP", "20")),
            min_score=float(e.get("MIN_SCORE", "60")),
            sender_name=e.get("SENDER_NAME", ""),
            sender_company=e.get("SENDER_COMPANY", "SupliiChain"),
            sender_address=e.get("SENDER_ADDRESS", ""),
            discovery=e.get("DISCOVERY", "csv"),
            research=e.get("RESEARCH", "fixture"),
            sender=e.get("SENDER", "dryrun"),
        )

    def use_anthropic(self) -> bool:
        if self.llm == "fake":
            return False
        if self.llm == "anthropic":
            return True
        return bool(self.anthropic_key)
