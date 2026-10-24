"""Code-enforced email compliance. The LLM never writes or removes this."""
from __future__ import annotations

from .config import Config


def footer(cfg: Config) -> str:
    addr = cfg.sender_address or "[SENDER_ADDRESS NOT SET]"
    return (f"\n\n--\n{cfg.sender_name or 'The team'}, {cfg.sender_company}\n{addr}\n"
            f"Not relevant? Reply \"unsubscribe\" and I won't contact you again.")


def ready_to_send(cfg: Config) -> list[str]:
    """Blocking problems for live sending (not required in dry-run)."""
    problems = []
    if not cfg.sender_address:
        problems.append("SENDER_ADDRESS (physical mailing address) is required by CAN-SPAM")
    if not cfg.sender_name:
        problems.append("SENDER_NAME is not set")
    return problems
