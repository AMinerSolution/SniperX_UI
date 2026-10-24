"""Pluggable I/O. Offline defaults: CSV discovery, fixture research, dry-run sender.
Real providers are explicit stubs that fail loudly rather than pretend to work."""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Iterable, Protocol

from .config import DATA, Config
from .models import Draft, Evidence, Lead


class Discovery(Protocol):
    def discover(self, icp, limit: int) -> Iterable[Lead]: ...


class Researcher(Protocol):
    def research(self, lead: Lead) -> list[Evidence]: ...


class Sender(Protocol):
    name: str

    def send(self, draft: Draft, lead: Lead) -> str: ...


def _int(v: str):
    v = (v or "").strip()
    return int(v) if v.isdigit() else None


class CsvDiscovery:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else DATA / "sample_leads.csv"

    def discover(self, icp, limit: int) -> Iterable[Lead]:
        with open(self.path, newline="", encoding="utf-8") as f:
            for i, row in enumerate(csv.DictReader(f)):
                if i >= limit:
                    break
                domain = row["domain"].strip().lower()
                yield Lead(
                    id=Lead.make_id(domain), company=row["company"], domain=domain,
                    contact_name=row.get("contact_name", ""), title=row.get("title", ""),
                    email=row.get("email", ""), linkedin=row.get("linkedin", ""),
                    employees=_int(row.get("employees", "")), gmv=_int(row.get("gmv", "")),
                    platform=row.get("platform", "").lower(), snippet=row.get("snippet", ""),
                    raw={"facts": row.get("facts", "")},
                )


class FixtureResearcher:
    """Reads pre-written facts from the CSV 'facts' column: kind::claim::quote | ... (offline testing only)."""

    def research(self, lead: Lead) -> list[Evidence]:
        out = []
        for chunk in re.split(r"\|(?=\w+::)", lead.raw.get("facts", "")):
            parts = chunk.split("::")
            if len(parts) != 3:
                continue
            kind, claim, quote = (p.strip() for p in parts)
            out.append(Evidence(lead_id=lead.id, claim=claim, quote=quote, kind=kind,
                                url=f"https://{lead.domain}/"))
        return out


class DryRunSender:
    name = "dryrun"

    def send(self, draft: Draft, lead: Lead) -> str:
        return f"dryrun-{draft.id}"


class _NotImplementedProvider:
    def __init__(self, what: str, env: str):
        self.what, self.env = what, env
        self.name = what

    def _fail(self, *a, **k):
        raise NotImplementedError(
            f"{self.what} provider is a stub. Implement it in swarm/providers.py (needs {self.env}) "
            f"or switch the matching env var back to the offline default.")

    discover = research = send = _fail


def make_discovery(cfg: Config, path: str | None = None) -> Discovery:
    if cfg.discovery == "csv":
        return CsvDiscovery(path)
    return _NotImplementedProvider("apollo-discovery", "APOLLO_API_KEY")  # type: ignore


def make_researcher(cfg: Config) -> Researcher:
    if cfg.research == "fixture":
        return FixtureResearcher()
    return _NotImplementedProvider("web-research", "a search/scrape API")  # type: ignore


def make_sender(cfg: Config) -> Sender:
    if cfg.sender == "dryrun" or cfg.dry_run:
        return DryRunSender()
    return _NotImplementedProvider("instantly-sender", "INSTANTLY_API_KEY")  # type: ignore
