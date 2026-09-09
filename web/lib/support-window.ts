/**
 * Remembering when a support window closes.
 *
 * The phase's hardest rule is that the remaining time is **always on
 * screen while reading customer data** -- access that expires silently
 * mid-read is worse than access that is refused. The API makes that
 * awkward: `GET …/support-access` is administrator rank, and the rank that
 * actually reads customer data is `support`, which cannot call it. The
 * only place a support engineer is ever told their expiry is the response
 * to their own request.
 *
 * So the console keeps what it was told. One cookie, a map of workspace id
 * to the `expires_at` the API returned, written when a grant is created
 * and dropped when one is ended.
 *
 * Three things keep this honest.
 *
 * It is a memory, never a permission. Every read is still refused by the
 * API if the grant is gone, and the screens render that refusal rather
 * than this value.
 *
 * It expires with the grant. Entries in the past are pruned on every read,
 * and the cookie's own life is the furthest expiry it holds -- so a
 * browser left alone over the weekend comes back holding nothing, exactly
 * as the grants themselves do.
 *
 * And it can only be stale in the visible direction: a grant revoked from
 * elsewhere leaves a countdown running beside reads that are refused,
 * which reads as "your window ended" the moment somebody opens anything.
 * The opposite -- a live grant the console has forgotten -- costs a
 * re-request, which is refused with `support_access_already_granted` and
 * says so.
 *
 * `httpOnly`, like the sessions: nothing in the browser needs to read it,
 * because the countdown gets the timestamp as a prop from the server.
 */

import { cookies } from "next/headers";

import { IS_PRODUCTION } from "@/lib/config";

const COOKIE = "baton_console_windows";

/** Workspace id to the ISO timestamp the API said the grant ends at. */
export type SupportWindows = Record<string, string>;

/**
 * One window, and the clock read that decided it was still open.
 *
 * The instant travels with the timestamp because the countdown on screen
 * has to start from the same moment the pruning below used. It is also
 * the only honest place to read a clock for a render: a component may not,
 * and this function is already impure -- it reads a cookie and compares it
 * to the time.
 */
export type SupportWindowSnapshot = { expiresAt: string; now: number };

function parse(value: string | undefined): SupportWindows {
  if (!value) return {};

  try {
    const parsed: unknown = JSON.parse(value);

    if (parsed === null || typeof parsed !== "object") return {};

    const windows: SupportWindows = {};

    for (const [id, expires] of Object.entries(parsed)) {
      if (typeof expires === "string") windows[id] = expires;
    }

    return windows;
  } catch {
    // Somebody's browser handed back something that is not our JSON. It
    // is a convenience, so the answer is to have forgotten rather than to
    // fail a page load over it.
    return {};
  }
}

/** What is still ahead of the clock, and nothing else. */
function live(windows: SupportWindows, now: number): SupportWindows {
  const kept: SupportWindows = {};

  for (const [id, expires] of Object.entries(windows)) {
    const at = Date.parse(expires);

    if (Number.isFinite(at) && at > now) kept[id] = expires;
  }

  return kept;
}

async function openWindows(): Promise<{ windows: SupportWindows; now: number }> {
  const now = Date.now();
  const store = await cookies();

  return { windows: live(parse(store.get(COOKIE)?.value), now), now };
}

export async function readSupportWindows(): Promise<SupportWindows> {
  return (await openWindows()).windows;
}

/** When this workspace's window closes, as far as this browser was told. */
export async function supportWindowFor(
  workspaceId: string,
): Promise<SupportWindowSnapshot | null> {
  const { windows, now } = await openWindows();
  const expiresAt = windows[workspaceId];

  return expiresAt ? { expiresAt, now } : null;
}

async function write(windows: SupportWindows): Promise<void> {
  const store = await cookies();

  if (Object.keys(windows).length === 0) {
    store.delete(COOKIE);

    return;
  }

  const furthest = Math.max(
    ...Object.values(windows).map((expires) => Date.parse(expires)),
  );

  store.set(COOKIE, JSON.stringify(windows), {
    httpOnly: true,
    secure: IS_PRODUCTION,
    sameSite: "lax" as const,
    path: "/",
    // Seconds until the last of them closes. The browser drops this at
    // the moment the grants it describes are all gone.
    maxAge: Math.max(1, Math.ceil((furthest - Date.now()) / 1000)),
  });
}

export async function rememberSupportWindow(
  workspaceId: string,
  expiresAt: string,
): Promise<void> {
  const windows = await readSupportWindows();

  await write({ ...windows, [workspaceId]: expiresAt });
}

export async function forgetSupportWindow(workspaceId: string): Promise<void> {
  const windows = await readSupportWindows();

  delete windows[workspaceId];

  await write(windows);
}
