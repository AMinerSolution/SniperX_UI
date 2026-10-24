import { auth } from 'app/auth';
import { notFound, redirect } from 'next/navigation';

// Comma-separated operator emails. Empty list = nobody (fail closed).
export function isAdmin(email?: string | null): boolean {
  let list = (process.env.SWARM_ADMIN_EMAILS || '')
    .split(',')
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
  return !!email && list.includes(email.trim().toLowerCase());
}

// Call at the top of every page AND every server action: middleware alone
// is not enough, server actions are directly invokable POST endpoints.
export async function requireAdmin(): Promise<string> {
  let session = await auth();
  let email = session?.user?.email;
  if (!email) redirect('/login');
  // Logged in but not allowlisted: 404, not /login (middleware bounces logged-in users back = redirect loop).
  if (!isAdmin(email)) notFound();
  return email;
}
