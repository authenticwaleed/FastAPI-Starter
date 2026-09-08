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

import {
  CONSOLE_ACCESS_COOKIE,
  CONSOLE_PATH,
  CONSOLE_REFRESH_COOKIE,
  CONSOLE_SIGN_IN_PATH,
  consoleRefreshCookieOptions,
} from "@/lib/console-session";
import { isSessionOver } from "@/lib/errors";
import { spendRefreshToken, type Refreshed } from "@/lib/refresh";
import {
  ACCESS_COOKIE,
  REFRESH_COOKIE,
  accessCookieOptions,
  refreshCookieOptions,
} from "@/lib/session";

/**
 * The platform console, which is guarded on its own terms below.
 *
 * Everything under here is answered by `forTheConsole` and nothing else in
 * this file, so a console request never spends the tenant refresh token
 * and a tenant request never spends the console's. The two surfaces do not
 * share a session, and this is where that starts.
 */
/**
 * Reachable without a session, and pointless with one.
 *
 * Signing in or registering while already signed in is somebody who has
 * lost their place, so these bounce to the app.
 */
const SIGNED_OUT_ONLY = ["/sign-in", "/register", "/forgot-password"];

/**
 * Reachable either way.
 *
 * These arrive as links in emails, and the common case is a person who is
 * already signed in -- registering signs you in, and the confirmation link
 * lands in the inbox a minute later. Bouncing those to the app throws away
 * the token they were carrying and leaves somebody clicking a link that
 * appears to do nothing.
 */
const ALWAYS_PUBLIC = [
  "/verify-email",
  "/reset-password",
  "/invitations",
  // The price list. Somebody deciding whether to sign up has no account
  // yet, and somebody signed in may well be comparing plans.
  "/pricing",
];

/**
 * A list of what is open rather than of what is closed, so a route added
 * next month is protected by default. Getting that the wrong way round is
 * how a screen ships unguarded.
 */
function matches(paths: string[], pathname: string): boolean {
  return paths.some((path) => pathname === path || pathname.startsWith(`${path}/`));
}

function isPublic(pathname: string): boolean {
  return matches(SIGNED_OUT_ONLY, pathname) || matches(ALWAYS_PUBLIC, pathname);
}

export async function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  if (pathname === CONSOLE_PATH || pathname.startsWith(`${CONSOLE_PATH}/`)) {
    return forTheConsole(request);
  }

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
  } else if (signedIn && matches(SIGNED_OUT_ONLY, pathname)) {
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

/**
 * The console's door, and its own idle clock.
 *
 * Three things this does that the tenant branch does not.
 *
 * It reads and writes only the console's cookies, so a 401 here cannot
 * end somebody's session in the customer app -- §3.5, and the reason the
 * console has a pair of its own at all.
 *
 * It re-stamps the refresh cookie on every request, which is how the idle
 * window rolls with use rather than with signing in. Sixty minutes with
 * nothing opened leaves the browser holding nothing to refresh with, and
 * the console asks who you are again -- mirroring the rule the API
 * enforces on `last_used_at` rather than quietly outliving it.
 *
 * And it never bounces a signed-in person away from the sign-in screen.
 * The API ending a console session leaves these cookies in place, so a
 * bounce would put somebody in a loop between a page that redirects here
 * and a screen that redirects back.
 */
async function forTheConsole(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  let accessToken = request.cookies.get(CONSOLE_ACCESS_COOKIE)?.value ?? null;
  const refreshToken = request.cookies.get(CONSOLE_REFRESH_COOKIE)?.value ?? null;

  let refreshed: Refreshed | null = null;
  let sessionEnded = false;

  if (!accessToken && refreshToken) {
    try {
      refreshed = await spendRefreshToken(refreshToken);
      accessToken = refreshed.access_token;

      request.cookies.set(CONSOLE_ACCESS_COOKIE, refreshed.access_token);
      request.cookies.set(CONSOLE_REFRESH_COOKIE, refreshed.refresh_token);
    } catch (error) {
      sessionEnded = isSessionOver(error);

      if (sessionEnded) {
        request.cookies.delete(CONSOLE_ACCESS_COOKIE);
        request.cookies.delete(CONSOLE_REFRESH_COOKIE);
      }
    }
  }

  let response: NextResponse;

  if (!accessToken && pathname !== CONSOLE_SIGN_IN_PATH) {
    const url = request.nextUrl.clone();
    url.pathname = CONSOLE_SIGN_IN_PATH;
    url.search = "";
    url.searchParams.set("next", `${pathname}${search}`);

    response = NextResponse.redirect(url);
  } else {
    response = NextResponse.next({ request: { headers: request.headers } });
  }

  if (refreshed) {
    response.cookies.set(
      CONSOLE_ACCESS_COOKIE,
      refreshed.access_token,
      accessCookieOptions(refreshed.expires_in),
    );
    response.cookies.set(
      CONSOLE_REFRESH_COOKIE,
      refreshed.refresh_token,
      consoleRefreshCookieOptions(),
    );
  } else if (refreshToken && !sessionEnded) {
    // The same token, with the idle window started again. Nothing is
    // spent: this is the browser being told the session is still in use.
    response.cookies.set(
      CONSOLE_REFRESH_COOKIE,
      refreshToken,
      consoleRefreshCookieOptions(),
    );
  }

  if (sessionEnded) {
    response.cookies.delete(CONSOLE_ACCESS_COOKIE);
    response.cookies.delete(CONSOLE_REFRESH_COOKIE);
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
