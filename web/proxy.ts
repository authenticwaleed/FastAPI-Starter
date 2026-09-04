/**
 * Refresh before the render, and keep signed-out people out.
 *
 * Next 16 renamed this convention from `middleware` to `proxy`, and its
 * documentation asks that it be a last resort. This is one of the cases
 * that has no alternative: a server component cannot set a cookie, so a
 * refresh performed during a render would spend the token and have nowhere
 * to put the new one -- and the next request would then present a token the
 * API has already rotated, which reads as a replay and ends the session.
 * Only something that runs before the render and owns the response can do
 * this correctly. Guarding routes is the other canonical use, and it is
 * here for the same reason: it has to happen before anything renders.
 *
 * An absent access cookie beside a present refresh cookie is not an error
 * and not a sign-out. It is the ordinary way a session says "refresh me".
 */

import { NextResponse, type NextRequest } from "next/server";

import { isSessionOver } from "@/lib/errors";
import { spendRefreshToken, type Refreshed } from "@/lib/refresh";
import {
  ACCESS_COOKIE,
  REFRESH_COOKIE,
  accessCookieOptions,
  refreshCookieOptions,
} from "@/lib/session";

/**
 * Reachable without a session.
 *
 * A list of what is open rather than of what is closed, so a route added
 * next month is protected by default. Getting that the wrong way round is
 * how a screen ships unguarded.
 */
const PUBLIC = [
  "/sign-in",
  "/register",
  "/verify-email",
  "/forgot-password",
  "/reset-password",
];

function isPublic(pathname: string): boolean {
  return PUBLIC.some((path) => pathname === path || pathname.startsWith(`${path}/`));
}

export async function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  let accessToken = request.cookies.get(ACCESS_COOKIE)?.value ?? null;
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value ?? null;

  let refreshed: Refreshed | null = null;
  let sessionEnded = false;

  if (!accessToken && refreshToken) {
    try {
      refreshed = await spendRefreshToken(refreshToken);
      accessToken = refreshed.access_token;

      // Written onto the *request* as well as the response below, so the
      // render that follows sees the new token rather than the absence
      // that started this.
      request.cookies.set(ACCESS_COOKIE, refreshed.access_token);
      request.cookies.set(REFRESH_COOKIE, refreshed.refresh_token);
    } catch (error) {
      // A spent or unknown refresh token is the end of the session.
      // Anything else -- the API down, a timeout -- is not, and must not
      // sign somebody out over an outage.
      sessionEnded = isSessionOver(error);

      if (sessionEnded) {
        request.cookies.delete(ACCESS_COOKIE);
        request.cookies.delete(REFRESH_COOKIE);
      }
    }
  }

  const signedIn = Boolean(accessToken);
  let response: NextResponse;

  if (!signedIn && !isPublic(pathname)) {
    const url = request.nextUrl.clone();
    url.pathname = "/sign-in";
    url.search = "";
    // Where they were headed, so signing in finishes the journey rather
    // than dropping them somewhere they did not ask for.
    url.searchParams.set("next", `${pathname}${search}`);

    response = NextResponse.redirect(url);
  } else if (signedIn && isPublic(pathname)) {
    const url = request.nextUrl.clone();
    url.pathname = "/";
    url.search = "";

    response = NextResponse.redirect(url);
  } else {
    // `request` inside `next()`, not alongside it: this makes the headers
    // visible to the render upstream. `NextResponse.next({ headers })`
    // would send them to the browser instead.
    response = NextResponse.next({ request: { headers: request.headers } });
  }

  if (refreshed) {
    response.cookies.set(
      ACCESS_COOKIE,
      refreshed.access_token,
      accessCookieOptions(refreshed.expires_in),
    );
    response.cookies.set(REFRESH_COOKIE, refreshed.refresh_token, refreshCookieOptions());
  }

  if (sessionEnded) {
    response.cookies.delete(ACCESS_COOKIE);
    response.cookies.delete(REFRESH_COOKIE);
  }

  return response;
}

export const config = {
  /**
   * Everything except the relay, Next's own assets, and files with an
   * extension. The relay at `/api/*` is left out because it refreshes and
   * retries for itself -- a route handler may set cookies, so it does not
   * need this -- and because a redirect to a sign-in page is the wrong
   * answer to somebody's `fetch`.
   */
  matcher: ["/((?!api|_next/static|_next/image|.*\\.).*)"],
};
