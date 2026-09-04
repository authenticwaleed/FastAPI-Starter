/**
 * The session, as two cookies the browser cannot read.
 *
 * Both are `httpOnly`, which is the whole point: the refresh token is the
 * durable credential -- it buys a new access token, and its life is the
 * session's -- so an XSS in this client must not be able to walk away with
 * it. Nothing in `app/` ever sees either value; the server attaches them.
 *
 * The access cookie deliberately expires with the access token. An absent
 * access cookie beside a present refresh cookie is not an error state, it
 * is the ordinary way a session says "refresh me", and the proxy
 * reads it exactly that way.
 */

import { cookies } from "next/headers";

import { IS_PRODUCTION, REFRESH_COOKIE_MAX_AGE } from "@/lib/config";

export const ACCESS_COOKIE = "baton_at";
export const REFRESH_COOKIE = "baton_rt";

/** What `/auth/login` and `/auth/refresh` return. */
export type TokenPair = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
};

export type Session = {
  accessToken: string | null;
  refreshToken: string | null;
};

/**
 * The options every session cookie carries.
 *
 * `sameSite: "lax"` is what stops another origin's form post arriving with
 * these attached, which is most of CSRF. It is not all of it -- a top-level
 * GET still carries them -- so the route handlers that mutate also check
 * the origin. Lax rather than strict because a person following an emailed
 * verification link arrives cross-site and should still be signed in.
 */
function options(maxAge: number) {
  return {
    httpOnly: true,
    secure: IS_PRODUCTION,
    sameSite: "lax" as const,
    path: "/",
    maxAge,
  };
}

export function accessCookieOptions(expiresIn: number) {
  // A little less than the token's own life, so the cookie is gone slightly
  // before the API would start refusing it. Refreshing early costs one
  // request; refreshing late costs a 401 on a page somebody is reading.
  return options(Math.max(expiresIn - 15, 5));
}

export function refreshCookieOptions() {
  return options(REFRESH_COOKIE_MAX_AGE);
}

/** The session on this request, for a server component or action. */
export async function readSession(): Promise<Session> {
  const store = await cookies();

  return {
    accessToken: store.get(ACCESS_COOKIE)?.value ?? null,
    refreshToken: store.get(REFRESH_COOKIE)?.value ?? null,
  };
}

/**
 * Write a fresh pair.
 *
 * Only callable where Next allows cookies to be set -- a route handler or a
 * server action. A server component cannot, which is why the refresh that
 * keeps a page load working lives in the proxy instead.
 */
export async function writeSession(pair: TokenPair): Promise<void> {
  const store = await cookies();

  store.set(ACCESS_COOKIE, pair.access_token, accessCookieOptions(pair.expires_in));
  store.set(REFRESH_COOKIE, pair.refresh_token, refreshCookieOptions());
}

export async function clearSession(): Promise<void> {
  const store = await cookies();

  store.delete(ACCESS_COOKIE);
  store.delete(REFRESH_COOKIE);
}
