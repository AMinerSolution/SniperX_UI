"""LLM abstraction. Agents call llm.json(task, ...). FakeLLM runs offline via per-task heuristics."""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Protocol

from .config import Config


class LLM(Protocol):
    def json(self, task: str, system: str, payload: dict, tier: str = "mid") -> dict: ...


class FakeLLM:
    """Deterministic stand-in. Each agent registers a heuristic for its task name."""

    def __init__(self) -> None:
        self.handlers: dict[str, Callable[[dict], dict]] = {}
        self.calls: list[tuple[str, str]] = []

    def register(self, task: str, fn: Callable[[dict], dict]) -> None:
        self.handlers[task] = fn

    def json(self, task: str, system: str, payload: dict, tier: str = "mid") -> dict:
        self.calls.append((task, tier))
        if task not in self.handlers:
            raise KeyError(f"FakeLLM has no handler for task '{task}'")
        return self.handlers[task](payload)


class AnthropicLLM:
    def __init__(self, cfg: Config):
        import anthropic

        self.client = anthropic.Anthropic(api_key=cfg.anthropic_key)
        self.models = {"cheap": cfg.model_cheap, "mid": cfg.model_mid, "top": cfg.model_top}
        self.calls: list[tuple[str, str]] = []

    def json(self, task: str, system: str, payload: dict, tier: str = "mid") -> dict:
        self.calls.append((task, tier))
        sys_prompt = system + "\n\nRespond with a single JSON object only. No prose, no code fences."
        last_err = ""
        for _ in range(2):
            user = json.dumps(payload, default=str)
            if last_err:
                user += f"\n\nYour previous reply was not valid JSON ({last_err}). Return JSON only."
            msg = self.client.messages.create(
                model=self.models[tier], max_tokens=1500, system=sys_prompt,
                messages=[{"role": "user", "content": user}],
            )
            text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
            text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
            try:
                return json.loads(text)
            except json.JSONDecodeError as e:
                last_err = str(e)
        raise ValueError(f"LLM task '{task}' did not return valid JSON: {last_err}")


def make_llm(cfg: Config) -> Any:
    return AnthropicLLM(cfg) if cfg.use_anthropic() else FakeLLM()
