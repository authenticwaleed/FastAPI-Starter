/**
 * Where the API is, and how long a cookie may live.
 *
 * Read in one place, so nothing else in the client has an opinion about
 * the API's address. It is never prefixed `NEXT_PUBLIC_`, because the
 * browser never calls FastAPI directly: everything it sends goes through
 * this application's own route handlers, which is what keeps the tokens
 * out of JavaScript.
 */

/**
 * The variable name, held in a constant rather than written inline.
 *
 * This is not style. `process.env.API_URL` spelled out is replaced by the
 * bundler with whatever the variable held when `next build` ran, and the
 * built server then ignores the environment it is actually started in --
 * so an image deployed with `API_URL=https://api.example.com` would go on
 * talking to localhost, silently, with nothing in any log to say why.
 *
 * A dynamic lookup cannot be folded into a literal, so the value is read
 * at request time from the process that is actually running.
 */
const API_URL_KEY = "API_URL";

/** Where the API is, as of this request. */
export function apiUrl(): string {
  return process.env[API_URL_KEY] ?? "http://localhost:8000";
}

/** `/api/v1`, spelled once. */
export const API_PREFIX = "/api/v1";

export const IS_PRODUCTION = process.env.NODE_ENV === "production";

/**
 * How long the refresh cookie lives.
 *
 * The API does not say -- a refresh token's life is the session's, and
 * that moves every time it is spent, so there is no number to be given in
 * advance. Fourteen days is a ceiling on the cookie rather than on the
 * session: the API is still the one that decides, and a cookie that
 * outlived the session would only mean a refresh that fails once and
 * signs the person out, which is the same place they end up anyway.
 */
export const REFRESH_COOKIE_MAX_AGE = 60 * 60 * 24 * 14;
