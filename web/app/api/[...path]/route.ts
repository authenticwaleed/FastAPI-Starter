/**
 * The relay: the only way out of the browser.
 *
 * Everything the client sends to the API arrives here first, gets the
 * bearer token attached from a cookie it cannot read, and is forwarded.
 * Nothing in the browser ever holds a token, which is the point of the
 * whole arrangement: an XSS in this client can make requests as the person
 * -- there is no defence against that -- but it cannot take the session
 * away and use it somewhere else, and it cannot take the refresh token at
 * all.
 *
 * Unlike a server component, a route handler may set cookies, so this
 * refreshes and retries for itself rather than leaning on the proxy.
 */

import { NextResponse, type NextRequest } from "next/server";

import { ApiError, isSessionOver } from "@/lib/errors";
import { spendRefreshToken } from "@/lib/refresh";
import { call } from "@/lib/api";
import {
  ACCESS_COOKIE,
  REFRESH_COOKIE,
  accessCookieOptions,
  refreshCookieOptions,
  type TokenPair,
} from "@/lib/session";

const READS = new Set(["GET", "HEAD", "OPTIONS"]);

/**
 * Refuse a mutation that came from somewhere else.
 *
 * `SameSite=Lax` already stops a cross-origin form post carrying the
 * session cookies, which is most of CSRF. This is the other half: a
 * same-site subdomain, or a browser that has not implemented Lax the way
 * this assumes, still has to present an Origin this application answers to.
 */
function fromAnotherOrigin(request: NextRequest): boolean {
  if (READS.has(request.method)) return false;

  const origin = request.headers.get("origin");

  // No Origin on a same-origin non-GET is unusual but legal in older
  // clients. `SameSite` is carrying it in that case.
  if (!origin) return false;

  try {
    return new URL(origin).host !== request.headers.get("host");
  } catch {
    return true;
  }
}

async function relay(request: NextRequest, path: string[]) {
  if (fromAnotherOrigin(request)) {
    return NextResponse.json(
      { detail: "This request did not come from here", code: "bad_origin" },
      { status: 403 },
    );
  }

  const target = `/${path.join("/")}${request.nextUrl.search}`;
  const body = READS.has(request.method) ? undefined : await request.text();

  const forwarded: Record<string, string> = {};
  const contentType = request.headers.get("content-type");

  if (contentType) forwarded["Content-Type"] = contentType;

  let response = await call(target, {
    method: request.method,
    raw: body,
    headers: forwarded,
  });

  let pair: TokenPair | null = null;

  if (response.status === 401) {
    const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;

    if (refreshToken) {
      try {
        pair = await spendRefreshToken(refreshToken);

        response = await call(target, {
          method: request.method,
          raw: body,
          headers: { ...forwarded, Authorization: `Bearer ${pair.access_token}` },
        });
      } catch (error) {
        // One refresh, one retry, and no loop. A spent token ends the
        // session; anything else leaves the original 401 to be reported.
        if (isSessionOver(error)) return signedOut(error);
      }
    }
  }

  const answer = new NextResponse(response.body, {
    status: response.status,
    headers: passThrough(response.headers),
  });

  if (pair) {
    answer.cookies.set(
      ACCESS_COOKIE,
      pair.access_token,
      accessCookieOptions(pair.expires_in),
    );
    answer.cookies.set(REFRESH_COOKIE, pair.refresh_token, refreshCookieOptions());
  }

  return answer;
}

function signedOut(error: ApiError) {
  const answer = NextResponse.json(
    { detail: error.detail, code: error.code },
    { status: 401 },
  );

  answer.cookies.delete(ACCESS_COOKIE);
  answer.cookies.delete(REFRESH_COOKIE);

  return answer;
}

/**
 * The response headers worth forwarding.
 *
 * A allowlist rather than the whole set: the API's `set-cookie` is not this
 * application's to relay, and its `content-length` will not match once the
 * body has been through a stream.
 */
function passThrough(headers: Headers): Headers {
  const kept = new Headers();

  for (const name of ["content-type", "retry-after", "www-authenticate"]) {
    const value = headers.get(name);

    if (value) kept.set(name, value);
  }

  return kept;
}

type Context = { params: Promise<{ path: string[] }> };

export async function GET(request: NextRequest, context: Context) {
  return relay(request, (await context.params).path);
}

export async function POST(request: NextRequest, context: Context) {
  return relay(request, (await context.params).path);
}

export async function PATCH(request: NextRequest, context: Context) {
  return relay(request, (await context.params).path);
}

export async function DELETE(request: NextRequest, context: Context) {
  return relay(request, (await context.params).path);
}
