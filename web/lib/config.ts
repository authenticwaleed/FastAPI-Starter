/**
 * Where the API is, and how long a cookie may live.
 *
 * Read once, here, so that nothing else in the client has an opinion about
 * the API's address. `API_URL` is server-only on purpose -- it is never
 * prefixed `NEXT_PUBLIC_`, because the browser never calls FastAPI
 * directly. Everything the browser sends goes through this application's
 * own route handlers, which is what keeps the tokens out of JavaScript.
 */

export const API_URL = process.env.API_URL ?? "http://localhost:8000";

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
