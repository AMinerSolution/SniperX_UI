// Server-side client for the Python swarm API. Never import from a client component:
// SWARM_API_TOKEN must not reach the browser.

export type DraftSummary = {
  id: number;
  kind: 'touch' | 'reply';
  step: number;
  channel: 'email' | 'linkedin';
  subject: string;
  status: string;
  score: number | null;
  lead: {
    id: string;
    company: string;
    domain: string;
    contact_name: string;
    title: string;
    email: string;
  };
};

export type Evidence = {
  id: number;
  claim: string;
  url: string;
  quote: string;
  kind: string;
};

export type DraftDetail = DraftSummary & {
  body: string;
  evidence: Evidence[];
  dry_run: boolean;
  replies: { label: string; body: string }[];
  score_detail: null | {
    icp_fit: number;
    tech_fit: number;
    intent: number;
    authority: number;
    urgency: number;
    composite: number;
    reasons: string[];
  };
};

export type Stats = {
  funnel: Record<string, number>;
  pending: number;
  sent_24h: number;
  daily_cap: number;
  dry_run: boolean;
};

export class SwarmError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function swarm<T>(path: string, init: RequestInit = {}): Promise<T> {
  let base = process.env.SWARM_API_URL;
  let token = process.env.SWARM_API_TOKEN;
  if (!base || !token) {
    throw new SwarmError(0, 'SWARM_API_URL / SWARM_API_TOKEN are not set');
  }
  let res: Response;
  try {
    res = await fetch(base.replace(/\/$/, '') + path, {
      ...init,
      cache: 'no-store',
      headers: {
        'content-type': 'application/json',
        authorization: `Bearer ${token}`,
        ...init.headers,
      },
    });
  } catch {
    throw new SwarmError(0, `Cannot reach the swarm API at ${base}`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {}
    throw new SwarmError(res.status, String(detail));
  }
  return res.json() as Promise<T>;
}
