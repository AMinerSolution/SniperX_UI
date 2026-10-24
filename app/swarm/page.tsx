import Link from 'next/link';
import { signOut } from 'app/auth';
import { requireAdmin } from 'app/swarm/access';
import { swarm, SwarmError, DraftSummary, Stats } from 'app/swarm/api';
import { advanceFollowups, runDiscovery } from 'app/swarm/actions';

export const dynamic = 'force-dynamic';

export default async function SwarmPage({
  searchParams,
}: {
  searchParams: { notice?: string; error?: string };
}) {
  let email = await requireAdmin();
  let stats: Stats | null = null;
  let queue: DraftSummary[] = [];
  let down: string | null = null;
  try {
    [stats, queue] = await Promise.all([
      swarm<Stats>('/stats'),
      swarm<DraftSummary[]>('/drafts?status=pending'),
    ]);
  } catch (e) {
    down = e instanceof SwarmError ? e.message : 'Swarm API unavailable';
  }

  return (
    <main className="mx-auto max-w-5xl space-y-6 p-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Approval queue</h1>
          <p className="text-sm text-gray-500">DPX outbound swarm · {email}</p>
        </div>
        <form
          action={async () => {
            'use server';
            await signOut();
          }}
        >
          <button className="text-sm text-gray-600 underline">Sign out</button>
        </form>
      </header>

      {searchParams.notice && (
        <p className="rounded-md bg-green-50 p-3 text-sm text-green-800">{searchParams.notice}</p>
      )}
      {(searchParams.error || down) && (
        <p className="rounded-md bg-red-50 p-3 text-sm text-red-800">{searchParams.error || down}</p>
      )}

      {stats && (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span
              className={`rounded-full px-3 py-1 font-medium ${
                stats.dry_run ? 'bg-amber-100 text-amber-900' : 'bg-red-600 text-white'
              }`}
            >
              {stats.dry_run ? 'DRY RUN · nothing is actually sent' : 'LIVE · approvals send real email'}
            </span>
            <span className="text-gray-600">
              Sent last 24h: {stats.sent_24h}/{stats.daily_cap}
            </span>
            <div className="ml-auto flex gap-2">
              <form action={runDiscovery}>
                <button className="rounded-md border px-3 py-1.5 hover:bg-gray-50">Run discovery</button>
              </form>
              <form action={advanceFollowups}>
                <button className="rounded-md border px-3 py-1.5 hover:bg-gray-50">Queue due follow-ups</button>
              </form>
            </div>
          </div>
          <div className="flex flex-wrap gap-2 text-xs">
            {Object.entries(stats.funnel).map(([k, v]) => (
              <span key={k} className="rounded bg-gray-100 px-2 py-1 text-gray-700">
                {k.replace(/_/g, ' ')}: <b>{v}</b>
              </span>
            ))}
          </div>
        </section>
      )}

      <section className="overflow-hidden rounded-lg border bg-white">
        {queue.length === 0 && !down ? (
          <p className="p-6 text-sm text-gray-500">Nothing waiting for approval. Run discovery to fill the queue.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="bg-gray-50 text-xs uppercase text-gray-500">
              <tr>
                <th className="p-3">#</th>
                <th className="p-3">Lead</th>
                <th className="p-3">Touch</th>
                <th className="p-3">Score</th>
                <th className="p-3">Subject</th>
                <th className="p-3" />
              </tr>
            </thead>
            <tbody className="divide-y">
              {queue.map((d) => (
                <tr key={d.id} className="hover:bg-gray-50">
                  <td className="p-3 text-gray-500">{d.id}</td>
                  <td className="p-3">
                    <div className="font-medium">{d.lead.company}</div>
                    <div className="text-xs text-gray-500">
                      {d.lead.contact_name || 'unknown'} · {d.lead.title}
                    </div>
                  </td>
                  <td className="p-3 whitespace-nowrap">
                    {d.kind === 'reply' ? (
                      <span className="rounded bg-blue-100 px-2 py-0.5 text-blue-800">reply</span>
                    ) : (
                      `#${d.step} ${d.channel}`
                    )}
                  </td>
                  <td className="p-3">{d.score ?? '-'}</td>
                  <td className="p-3 text-gray-700">{d.subject || '(LinkedIn note)'}</td>
                  <td className="p-3 text-right">
                    <Link href={`/swarm/drafts/${d.id}`} className="font-semibold text-gray-900 underline">
                      Review
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </main>
  );
}
