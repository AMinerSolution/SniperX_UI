'use server';

import { revalidatePath } from 'next/cache';
import { redirect } from 'next/navigation';
import { requireAdmin } from 'app/swarm/access';
import { swarm, SwarmError } from 'app/swarm/api';

function back(kind: 'notice' | 'error', msg: string): never {
  revalidatePath('/swarm');
  redirect(`/swarm?${kind}=${encodeURIComponent(msg)}`);
}

async function run(fn: () => Promise<string>): Promise<never> {
  let result: { kind: 'notice' | 'error'; msg: string };
  try {
    result = { kind: 'notice', msg: await fn() };
  } catch (e) {
    result = { kind: 'error', msg: e instanceof SwarmError ? e.message : 'Unexpected error' };
  }
  return back(result.kind, result.msg);
}

export async function approveDraft(formData: FormData) {
  await requireAdmin();
  let id = Number(formData.get('id'));
  let body = formData.get('body');
  return run(async () => {
    let r = await swarm<{ lead_status: string }>(`/drafts/${id}/approve`, {
      method: 'POST',
      body: JSON.stringify({ body: typeof body === 'string' ? body : null }),
    });
    return `Draft #${id} approved. Lead is now "${r.lead_status}".`;
  });
}

export async function rejectDraft(formData: FormData) {
  await requireAdmin();
  let id = Number(formData.get('id'));
  return run(async () => {
    await swarm(`/drafts/${id}/reject`, { method: 'POST' });
    return `Draft #${id} rejected.`;
  });
}

export async function runDiscovery() {
  await requireAdmin();
  return run(async () => {
    let r = await swarm<{ counts: Record<string, number> }>('/run', {
      method: 'POST',
      body: JSON.stringify({ limit: 50 }),
    });
    let c = r.counts;
    return `Discovery done: ${c.passed} passed filter, ${c.filtered_out} filtered out, ${c.duplicate} already known.`;
  });
}

export async function advanceFollowups() {
  await requireAdmin();
  return run(async () => {
    let r = await swarm<{ started: string[] }>('/tick', {
      method: 'POST',
      body: JSON.stringify({ days: 0 }),
    });
    return `${r.started.length} follow-up draft(s) queued.`;
  });
}
