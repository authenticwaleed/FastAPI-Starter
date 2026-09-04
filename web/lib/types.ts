/**
 * Shapes the API returns.
 *
 * Hand-written for W1 and deliberately few. Decision 5.5 of the plan is
 * that these come from the committed schema by way of `openapi-typescript`,
 * and the generator lands with the phase that first needs a shape too large
 * to be worth typing out. Until then, one small file that says what these
 * four endpoints answer with beats a generated 6,000-line union nothing yet
 * reads.
 */

/** `GET /auth/me`, and what `/account` returns. */
export type User = {
  id: number;
  name: string;
  email: string;
  is_active: boolean;
  /**
   * Null until somebody follows the link sent to this address, and null
   * again when the address changes. Nothing in the API is gated on it, so
   * this client nudges rather than locks.
   */
  email_verified_at: string | null;
  created_at: string;
  updated_at: string;
};
