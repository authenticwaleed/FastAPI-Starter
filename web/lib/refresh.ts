/**
 * Spending a refresh token, at most once at a time.
 *
 * The API rotates: refreshing spends the token and returns a new one, and
 * presenting a spent one answers `refresh_token_reused`, which is a
 * deliberate hard stop rather than a retryable error -- it means somebody
 * replayed a token, and the honest response is to end the session.
 *
 * That makes concurrency the whole problem here. One page load fires
 * several requests; if two of them notice the access token has expired and
 * both refresh, the second presents a token the first has already spent and
 * signs a perfectly innocent person out.
 *
 * So refreshes are keyed on the token being spent and shared. Two callers
 * holding the same refresh token get the same promise and the same new
 * pair.
 *
 * The map is an optimisation and nothing depends on it. Next's own
 * documentation asks that a proxy not rely on shared module state, because
 * in optimised deployments it can run somewhere that has none; two
 * instances behind a load balancer can race here whatever this file does,
 * and the API is right to refuse the loser. What the map buys, in the
 * Node runtime a proxy actually defaults to, is that the several requests
 * of one page load do not sign an innocent person out. Correctness is the
 * API's rotation check; this is courtesy.
 */

import { API_PREFIX, API_URL } from "@/lib/config";
import { errorFrom } from "@/lib/errors";
import type { TokenPair } from "@/lib/session";

/** What a refresh returns. Named so a caller need not import the session. */
export type Refreshed = TokenPair;

const inFlight = new Map<string, Promise<TokenPair>>();

export async function spendRefreshToken(refreshToken: string): Promise<TokenPair> {
  const existing = inFlight.get(refreshToken);

  if (existing) return existing;

  const attempt = exchange(refreshToken).finally(() => {
    inFlight.delete(refreshToken);
  });

  inFlight.set(refreshToken, attempt);

  return attempt;
}

async function exchange(refreshToken: string): Promise<TokenPair> {
  const response = await fetch(`${API_URL}${API_PREFIX}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
    // This is a credential exchange. Nothing about it may be cached.
    cache: "no-store",
  });

  if (!response.ok) throw await errorFrom(response);

  return (await response.json()) as TokenPair;
}
