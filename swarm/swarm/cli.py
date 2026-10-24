"""swarm CLI: the human-in-the-loop console until the Next.js UI exists."""
from __future__ import annotations

import argparse
import json
import sys
import time

from .agents import discovery, inbox, meeting
from .context import build_ctx
from .graph import build_graph, decide, run_lead, tick


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="swarm")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="discover -> filter -> research -> qualify -> draft (stops at approval)")
    r.add_argument("--limit", type=int, default=50)
    r.add_argument("--csv", help="leads CSV (default: bundled fixtures)")
    sub.add_parser("review", help="list drafts awaiting approval")
    s = sub.add_parser("show"); s.add_argument("draft_id", type=int)
    a = sub.add_parser("approve"); a.add_argument("draft_id", type=int); a.add_argument("--body-file")
    x = sub.add_parser("reject"); x.add_argument("draft_id", type=int)
    t = sub.add_parser("tick", help="advance due follow-ups"); t.add_argument("--days", type=float, default=0, help="simulate N days passing")
    rp = sub.add_parser("reply", help="feed an inbound reply"); rp.add_argument("lead"); rp.add_argument("text")
    b = sub.add_parser("brief"); b.add_argument("lead")
    tr = sub.add_parser("trace"); tr.add_argument("lead")
    sub.add_parser("stats")
    args = p.parse_args(argv)

    ctx = build_ctx(run_id=f"cli-{int(time.time())}")
    if args.cmd == "run":
        from .providers import CsvDiscovery
        if args.csv:
            ctx.discovery = CsvDiscovery(args.csv)
        graph = build_graph(ctx)
        found = discovery.run(ctx, args.limit)
        print({k: len(v) for k, v in found.items()})
        for lid in found["passed"]:
            print(f"  {ctx.mem.get_lead(lid).company:28} -> {run_lead(ctx, graph, lid)}")
        print("Next: `swarm review`")
        return 0
    graph = build_graph(ctx)
    if args.cmd == "review":
        for d in ctx.mem.drafts(status="pending"):
            lead = ctx.mem.get_lead(d.lead_id); sc = ctx.mem.get_score(d.lead_id)
            print(f"#{d.id} [{d.kind} step {d.step} {d.channel}] {lead.company} <{lead.email}> score={sc.composite if sc else '-'}  {d.subject}")
    elif args.cmd == "show":
        d = ctx.mem.get_draft(args.draft_id)
        print(f"Subject: {d.subject}\n\n{d.body}\n\nEvidence:")
        ev = {e.id: e for e in ctx.mem.evidence(d.lead_id)}
        for i in d.evidence_ids:
            print(f"  [{i}] {ev[i].claim} - {ev[i].url} \"{ev[i].quote}\"")
    elif args.cmd in ("approve", "reject"):
        body = open(args.body_file).read() if getattr(args, "body_file", None) else None
        print("lead status:", decide(ctx, graph, args.draft_id, args.cmd, body))
    elif args.cmd == "tick":
        print("follow-ups started:", tick(ctx, graph, time.time() + args.days * 86400))
    elif args.cmd in ("reply", "brief", "trace"):
        lead = ctx.mem.find_lead(args.lead)
        if not lead:
            print("unknown lead", file=sys.stderr); return 1
        if args.cmd == "reply":
            print(inbox.handle(ctx, lead.id, args.text))
        elif args.cmd == "brief":
            print(meeting.brief(ctx, lead.id))
        else:
            for e in ctx.mem.trace(lead.id):
                print(f"{e['agent']:10} {e['kind']:14} {e['data'][:140]}")
    elif args.cmd == "stats":
        print(json.dumps(ctx.mem.funnel(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
