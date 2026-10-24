import Link from 'next/link';
import { notFound } from 'next/navigation';
import { requireAdmin } from 'app/swarm/access';
import { swarm, SwarmError, DraftDetail } from 'app/swarm/api';
import { approveDraft, rejectDraft } from 'app/swarm/actions';

export const dynamic = 'force-dynamic';

const FOOTER_MARKER = '\n\n--\n';
const CRITERIA = ['icp_fit', 'tech_fit', 'intent', 'authority', 'urgency'] as const;

// Only http(s) links are rendered as links: evidence URLs come from scraped data.
function safeHref(url: string): string | null {
  try {
    let u = new URL(url);
    return u.protocol === 'http:' || u.protocol === 'https:' ? u.href : null;
  } catch {
    return null;
  }
}

export default async function DraftPage({ params }: { params: { id: string } }) {
  await requireAdmin();
  let id = Number(params.id);
  if (!Number.isInteger(id)) notFound();

  let d: DraftDetail;
  try {
    d = await swarm<DraftDetail>(`/drafts/${id}`);
  } catch (e) {
    if (e instanceof SwarmError && e.status === 404) notFound();
    throw e;
  }

  let hasFooter = d.channel === 'email' && d.body.includes(FOOTER_MARKER);
  let editable = hasFooter ? d.body.split(FOOTER_MARKER)[0] : d.body;
  let footer = hasFooter ? FOOTER_MARKER.trimStart() + d.body.split(FOOTER_MARKER).slice(1).join(FOOTER_MARKER) : '';
  let pending = d.status === 'pending';
  let lastReply = d.replies.length ? d.replies[d.replies.length - 1] : null;

  return (
    <main className="mx-auto max-w-5xl space-y-5 p-6">
      <Link href="/swarm" className="text-sm text-gray-600 underline">
        ← Queue
      </Link>
      <h1 className="text-xl font-semibold">
        #{d.id} · {d.lead.company}{' '}
        <span className="text-base font-normal text-gray-500">
          {d.kind === 'reply' ? 'reply draft' : `touch ${d.step} (${d.channel})`}
        </span>
      </h1>

      {d.kind === 'reply' && lastReply && (
        <div className="rounded-md border-l-4 border-blue-400 bg-blue-50 p-3 text-sm">
          <div className="text-xs font-medium uppercase text-blue-800">Prospect wrote ({lastReply.label})</div>
          <p className="mt-1 whitespace-pre-wrap">{lastReply.body}</p>
        </div>
      )}

      <div className="grid gap-5 md:grid-cols-5">
        <form className="space-y-3 md:col-span-3">
          <input type="hidden" name="id" value={d.id} />
          <div className="rounded-lg border bg-white p-4 text-sm">
            <div className="text-gray-500">
              To: {d.lead.contact_name || 'unknown'} &lt;{d.lead.email}&gt;
            </div>
            <div className="mt-1 font-medium">{d.subject || '(LinkedIn note, no subject)'}</div>
            <textarea
              name="body"
              defaultValue={editable}
              rows={12}
              disabled={!pending}
              className="mt-3 w-full rounded-md border p-2 font-mono text-sm disabled:bg-gray-50"
            />
            {footer && (
              <pre className="mt-2 whitespace-pre-wrap rounded bg-gray-50 p-2 text-xs text-gray-500">
                {footer}
                {'\n'}(compliance footer, added automatically, cannot be removed)
              </pre>
            )}
          </div>

          {pending ? (
            <div className="flex gap-3">
              <button
                formAction={approveDraft}
                className={`rounded-md px-4 py-2 text-sm font-semibold text-white ${
                  d.dry_run ? 'bg-gray-900' : 'bg-red-600'
                }`}
              >
                {d.dry_run ? 'Approve (dry run, no email leaves)' : 'Approve & SEND for real'}
              </button>
              <button formAction={rejectDraft} className="rounded-md border px-4 py-2 text-sm">
                Reject
              </button>
            </div>
          ) : (
            <p className="text-sm text-gray-500">This draft is {d.status}; no further action.</p>
          )}
        </form>

        <aside className="space-y-4 md:col-span-2">
          <section className="rounded-lg border bg-white p-4 text-sm">
            <h2 className="mb-2 font-semibold">Why this lead ({d.score ?? '-'}/100)</h2>
            {d.score_detail && (
              <ul className="space-y-1">
                {CRITERIA.map((k) => (
                  <li key={k} className="flex items-center gap-2">
                    <span className="w-20 text-gray-500">{k.replace('_', ' ')}</span>
                    <span className="h-2 flex-1 rounded bg-gray-100">
                      <span
                        className="block h-2 rounded bg-gray-800"
                        style={{ width: `${(d.score_detail![k] / 5) * 100}%` }}
                      />
                    </span>
                    <span className="w-8 text-right">{d.score_detail![k]}</span>
                  </li>
                ))}
              </ul>
            )}
            {d.score_detail?.reasons.map((r, i) => (
              <p key={i} className="mt-2 text-xs text-gray-500">
                {r}
              </p>
            ))}
          </section>

          <section className="rounded-lg border bg-white p-4 text-sm">
            <h2 className="mb-2 font-semibold">Evidence the draft relies on</h2>
            {d.evidence.length === 0 && <p className="text-gray-500">None cited.</p>}
            {d.evidence.map((e) => {
              let href = safeHref(e.url);
              return (
                <div key={e.id} className="mb-3 last:mb-0">
                  <p className="font-medium">{e.claim}</p>
                  <blockquote className="border-l-2 pl-2 text-gray-600">“{e.quote}”</blockquote>
                  {href ? (
                    <a href={href} target="_blank" rel="noopener noreferrer" className="text-xs text-blue-700 underline">
                      {href}
                    </a>
                  ) : (
                    <span className="text-xs text-gray-400">no valid source link</span>
                  )}
                </div>
              );
            })}
          </section>
        </aside>
      </div>
    </main>
  );
}
