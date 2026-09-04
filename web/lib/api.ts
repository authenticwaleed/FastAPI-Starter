/**
 * Calling the API from the server.
 *
 * The only module that talks to FastAPI. A server component reads through
 * `api()`, a server action writes through it, and the browser reaches it
 * through the relay route handler -- so there is one place that knows the
 * API's address, one that attaches the bearer token, and none in `app/`.
 *
 * Refreshing is not done here. A server component cannot set a cookie, so a
 * refresh performed during a render would be spent and then thrown away,
 * and the next request would present a token the API has already rotated.
 * The proxy refreshes before the render instead; this module assumes
 * whatever it finds in the cookie is the best available and reports a 401
 * honestly.
 */

import { API_PREFIX, API_URL } from "@/lib/config";
import { ApiError, errorFrom } from "@/lib/errors";
import { readSession } from "@/lib/session";

type Options = Omit<RequestInit, "body"> & {
  /** Serialised as JSON. Pass a FormData through `raw` instead. */
  json?: unknown;
  raw?: BodyInit;
  /** Skip the bearer token, for the handful of endpoints that take none. */
  anonymous?: boolean;
};

/**
 * One request, returning the parsed body or throwing an `ApiError`.
 *
 * Throwing rather than returning a union is deliberate: nearly every caller
 * either has the value or has nothing to render, and a `try` around the
 * ones that want to handle a specific code reads better than an `if` at
 * every call site that does not.
 */
export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const response = await call(path, options);

  if (!response.ok) throw await errorFrom(response);

  // 204, and the handful of endpoints that answer with no body.
  if (response.status === 204 || response.headers.get("content-length") === "0") {
    return undefined as T;
  }

  return (await response.json()) as T;
}

/** The same request, handed back unread. For the proxy, which streams it on. */
export async function call(path: string, options: Options = {}): Promise<Response> {
  const { json, raw, anonymous, headers, ...rest } = options;

  const sent = new Headers(headers);

  if (!anonymous) {
    const { accessToken } = await readSession();

    if (accessToken) sent.set("Authorization", `Bearer ${accessToken}`);
  }

  if (json !== undefined && !sent.has("Content-Type")) {
    sent.set("Content-Type", "application/json");
  }

  return fetch(`${API_URL}${API_PREFIX}${path}`, {
    ...rest,
    headers: sent,
    body: json !== undefined ? JSON.stringify(json) : raw,
    // Everything here is either a person's own data or a mutation. Neither
    // is cacheable, and a cached workspace belonging to the previous
    // visitor is the worst bug this client could have.
    cache: "no-store",
  });
}

/**
 * The same as `api`, but `null` instead of throwing on a 404.
 *
 * For the reads where absence is an ordinary answer -- no subscription yet,
 * no storefront connected -- rather than a failure worth a screen.
 */
export async function apiOrNull<T>(
  path: string,
  options: Options = {},
): Promise<T | null> {
  try {
    return await api<T>(path, options);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;

    throw error;
  }
}
