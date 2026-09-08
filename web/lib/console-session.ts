/**
 * The console's session, held apart from the customer app's.
 *
 * §3.5 of the plan: `/admin/*` refuses a session that has been left idle
 * while that same session keeps working on the tenant surface. So the
 * console needs its own way back in, and a 401 there must leave the tenant
 * session alone.
 *
 * The obvious reading of that -- share the cookies, sign in again into the
 * same pair -- fails twice.
 *
 * Signing in mints a *new* session, so re-authenticating for the console
 * would replace the one the customer app is holding and orphan it at the
 * API. That is precisely what §3.5 asks not to happen.
 *
 * And a shared pair would inherit its liveness from the busier surface.
 * The app refreshes whenever its access token runs out, every rotation
 * moves the session's `last_used_at`, and the console would then never be
 * idle however long nobody looked at it -- an API rule quietly evaded by
 * its own client. §1 is clear about which of the two is right when they
 * disagree.
 *
 * So the console holds two cookies of its own, written only by its own
 * sign-in, read only by `lib/console.ts`, and never touched by anything
 * under `(app)`.
 */

import { cookies } from "next/headers";

import {
  accessCookieOptions,
  cookieOptions,
  type Session,
  type TokenPair,
} from "@/lib/session";

/**
 * Where the console lives, spelled once.
 *
 * Here rather than in `lib/console.ts` because the proxy needs both and
 * must not pull the reads -- and their `next/headers` -- in behind them.
 */
export const CONSOLE_PATH = "/console";
export const CONSOLE_SIGN_IN_PATH = "/console/sign-in";

export const CONSOLE_ACCESS_COOKIE = "baton_console_at";
export const CONSOLE_REFRESH_COOKIE = "baton_console_rt";

/**
 * How long a console session may sit unused in this browser.
 *
 * The API's own limit is `admin_session_idle_minutes` -- sixty by default
 * -- measured from the session row's `last_used_at`. This mirrors it as
 * the refresh cookie's life, re-stamped on every console request by the
 * proxy, so an hour with nothing opened leaves the browser holding nothing
 * to refresh with and the console asks who you are again.
 *
 * A mirror, not the rule. The API decides, and it answers
 * `admin_session_expired` where the two ever disagree. Being the stricter
 * of the pair is the safe direction to be wrong in.
 */
export const CONSOLE_IDLE_MAX_AGE = 60 * 60;

export function consoleRefreshCookieOptions() {
  return cookieOptions(CONSOLE_IDLE_MAX_AGE);
}

/** The console session on this request, for a server component or action. */
export async function readConsoleSession(): Promise<Session> {
  const store = await cookies();

  return {
    accessToken: store.get(CONSOLE_ACCESS_COOKIE)?.value ?? null,
    refreshToken: store.get(CONSOLE_REFRESH_COOKIE)?.value ?? null,
  };
}

export async function writeConsoleSession(pair: TokenPair): Promise<void> {
  const store = await cookies();

  store.set(
    CONSOLE_ACCESS_COOKIE,
    pair.access_token,
    accessCookieOptions(pair.expires_in),
  );
  store.set(CONSOLE_REFRESH_COOKIE, pair.refresh_token, consoleRefreshCookieOptions());
}

/** Ends the console session, and only that one. */
export async function clearConsoleSession(): Promise<void> {
  const store = await cookies();

  store.delete(CONSOLE_ACCESS_COOKIE);
  store.delete(CONSOLE_REFRESH_COOKIE);
}
