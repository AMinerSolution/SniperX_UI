# DPX Outbound Swarm

LangGraph relay that takes Demand Planner X (DPX) from ICP to booked-call brief. Offline-first: with no API keys it runs on a deterministic FakeLLM, fixture leads, and a dry-run sender. Nothing leaves the system until you flip it.

```
discovery -> prefilter (rules, cheap LLM only if unsure)      [batch]
  per lead: research -> qualify (5 criteria, evidence-gated) -> draft (grounded) -> HUMAN APPROVAL (interrupt) -> send
inbox: classify reply -> suppress | snooze | closer draft (KB-grounded, human approves) ; meeting brief from memory
```

## Run it (offline)
```bash
cd swarm && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env            # optional; defaults are safe
python -m swarm run             # 12 fixture leads -> 5 drafts waiting
python -m swarm review          # approval queue
python -m swarm show 1          # draft + the evidence behind it
python -m swarm approve 1       # (--body-file edited.txt to edit) ; or: reject 1
python -m swarm tick --days 4   # simulate time: queues Day-4 follow-ups for approval
python -m swarm reply northwindpet.example "how much does it cost?"
python -m swarm brief northwindpet.example
python -m swarm trace northwindpet.example   # every handoff, in order
python -m swarm stats
pytest -q
```

## Approval UI (Next.js, `/swarm`)
```
# 1. swarm API (needs a token; refuses to start without one)
cd swarm && SWARM_API_TOKEN=<secret> python -m swarm.api          # 127.0.0.1:8000
# 2. web app: set in the repo-root .env (see .env.example)
#    POSTGRES_URL, AUTH_SECRET, SWARM_ADMIN_EMAILS=you@x.com, SWARM_API_URL=http://127.0.0.1:8000, SWARM_API_TOKEN=<same secret>
pnpm dev    # sign up with an allowlisted email at /register, then /swarm
```
Access: sign-up is closed to everyone not in `SWARM_ADMIN_EMAILS`; every page and server action re-checks the allowlist (empty list = nobody).
The API token stays server-side. The browser never talks to the Python API. Edits to a draft can't remove the unsubscribe footer.
The Python API holds the state and the paused LangGraph checkpoints, so host it somewhere persistent (VM/container with a volume), not on Vercel.

## Docker (API only)
```
cd swarm && cp .env.example .env     # set SWARM_API_TOKEN (and ANTHROPIC_API_KEY later)
docker compose up -d --build         # API on 127.0.0.1:8000, data in the `swarm-data` volume
```
- `/data` must be a persistent volume: it holds the memory DB and the paused approval checkpoints (survive restarts, verified).
- Run exactly one container/process (SQLite + in-process lock). Don't scale it or add `--workers`.
- Port is bound to localhost. To reach it from Vercel, put TLS in front (Fly/Railway/Caddy) and keep the bearer token secret.
- Runs as a non-root user. Healthcheck sends the token to `/health`.

## Guardrails (enforced in code, not prompts)
- No send without an approved draft; `DRY_RUN=true` by default; `DAILY_SEND_CAP`.
- Draft must cite evidence ids that exist; any number not in evidence/product facts is rejected; price/ROI/guarantee language is banned.
- Qualifier zeroes intent/urgency unless it cites real evidence ids. LLM tiebreak only within 5 pts of `MIN_SCORE`.
- Unsubscribe replies are detected by regex before any model, suppress the address, and cancel queued drafts.
- Live sending is blocked until `SENDER_ADDRESS` and `SENDER_NAME` are set (CAN-SPAM footer is appended by code).
- A lead is never discovered twice (domain-unique memory).

## Going live (one switch at a time)
| Switch | Env | Status |
|---|---|---|
| Real LLM (haiku filter / sonnet judge+draft / opus closer) | `ANTHROPIC_API_KEY` | wired, untested without a key |
| Apollo discovery | `DISCOVERY=apollo` | **stub** in `providers.py` |
| Web/Clay research | `RESEARCH=web` | **stub** |
| Instantly sending | `SENDER=instantly`, `DRY_RUN=false` | **stub** |

## Before first real send
Edit `swarm/data/product.md` and `kb.md`: they currently contain only assumptions about DPX (no pricing, no metrics). The swarm can only claim what is written there.
