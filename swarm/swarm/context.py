from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from .config import DATA, Config
from .llm import FakeLLM, make_llm
from .memory import Memory
from .models import ICP
from .providers import Discovery, Researcher, Sender, make_discovery, make_researcher, make_sender


@dataclass
class Ctx:
    cfg: Config
    mem: Memory
    llm: Any
    icp: ICP
    discovery: Discovery
    researcher: Researcher
    sender: Sender
    product_facts: str
    kb: str
    run_id: str = "run"

    def log(self, lead_id: Optional[str], agent: str, kind: str, data: Any = None) -> None:
        self.mem.event(self.run_id, lead_id, agent, kind, data)


def load_icp(path: str | None = None) -> ICP:
    from pathlib import Path

    return ICP(**json.loads(Path(path or DATA / "icp_dpx.json").read_text()))


def build_ctx(cfg: Optional[Config] = None, mem: Optional[Memory] = None, llm: Any = None,
              icp: Optional[ICP] = None, discovery: Any = None, researcher: Any = None,
              sender: Any = None, run_id: str = "run") -> Ctx:
    from .agents import discovery as a_disc, inbox, outreach, qualifier

    cfg = cfg or Config.from_env()
    llm = llm or make_llm(cfg)
    if isinstance(llm, FakeLLM):
        for mod in (a_disc, qualifier, outreach, inbox):
            mod.register_fake(llm)
    return Ctx(
        cfg=cfg, mem=mem or Memory(cfg.db_path), llm=llm, icp=icp or load_icp(),
        discovery=discovery or make_discovery(cfg), researcher=researcher or make_researcher(cfg),
        sender=sender or make_sender(cfg),
        product_facts=(DATA / "product.md").read_text(), kb=(DATA / "kb.md").read_text(), run_id=run_id,
    )
