/**
 * The one place a refusal becomes a sentence.
 *
 * Every failure the API returns has the same shape -- `detail`, `code`, and
 * `errors` on a validation failure -- and `code` is the stable half.
 * `detail` is prose the API is free to reword, so nothing here or anywhere
 * else branches on it.
 *
 * One module, because a screen that invents its own wording for a 409 is a
 * screen that will disagree with the next one. Adding an endpoint means
 * adding its codes here, not writing a message at the call site.
 */

/** A per-field entry, present only on a validation failure. */
export type FieldError = {
  loc: (string | number)[];
  msg: string;
  type?: string;
};

export type ErrorBody = {
  detail: string;
  code: string;
  errors?: FieldError[] | null;
};

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string;
  readonly errors: FieldError[];
  /** Seconds to wait, from `Retry-After`. Only ever set on a 429. */
  readonly retryAfter: number | null;

  constructor(status: number, body: ErrorBody, retryAfter: number | null = null) {
    super(`${status} ${body.code}: ${body.detail}`);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.detail = body.detail;
    this.errors = body.errors ?? [];
    this.retryAfter = retryAfter;
  }

  /** What to show a person. */
  get sentence(): string {
    return sentenceFor(this.code, this.detail);
  }

  /**
   * Field errors keyed by field name, ready for a form.
   *
   * `loc` is a path like `["body", "email"]`; the last element is the
   * field, which is what a form input is named after.
   */
  get fields(): Record<string, string> {
    const found: Record<string, string> = {};

    for (const error of this.errors) {
      const name = error.loc.at(-1);

      if (typeof name === "string" && !(name in found)) {
        found[name] = error.msg;
      }
    }

    return found;
  }
}

/**
 * Codes to sentences.
 *
 * Grouped by where they come from so that adding a phase's endpoints means
 * adding a block, not hunting through an alphabetical list. W1 covers
 * authentication and the refusals any request can meet; later phases append.
 */
export const SENTENCES: Record<string, string> = {
  // --- authenticating -----------------------------------------------------
  invalid_credentials: "That email and password do not match an account.",
  inactive_user: "This account has been deactivated. Ask an owner to restore it.",
  incorrect_password: "That is not your current password.",
  email_already_exists: "An account with that address already exists.",
  user_not_found: "No account with that address.",

  // --- the session --------------------------------------------------------
  invalid_refresh_token: "Your session has ended. Sign in again.",
  // Deliberately the same sentence as above. The distinction matters to the
  // client -- this one means stop retrying and throw the tokens away -- and
  // it means nothing to the person, who has one thing to do either way.
  refresh_token_reused: "Your session has ended. Sign in again.",
  session_not_found: "That session has already ended.",

  // --- links that were emailed --------------------------------------------
  invalid_verification_token:
    "This link is no longer valid. It may have been used already, or expired.",

  // --- the account, and its workspaces (W2) -------------------------------
  // `workspace_not_found` covers "no such workspace" and "you are not a
  // member of it" alike. The API answers both the same way on purpose, so
  // an id cannot be used to discover which businesses have accounts, and
  // this sentence must not be more helpful than that.
  workspace_not_found: "No such workspace.",
  slug_already_exists: "That address is taken. Try another.",
  insufficient_workspace_role: "Your role in this workspace does not allow this.",
  // 403, and about an operational decision rather than a plan or a role.
  // The copy must not imply the customer failed to pay.
  workspace_suspended:
    "This workspace is suspended, so it cannot be changed. Its data is still here.",
  workspace_ownership_required:
    "You are the only owner of a workspace. Hand it over or close it first.",
  last_owner: "A workspace has to keep at least one owner.",
  membership_not_found: "That person is not in this workspace.",
  notification_not_found: "That notification is no longer there.",

  // --- anything, anywhere -------------------------------------------------
  rate_limit_exceeded: "Too many attempts. Wait a moment and try again.",
  validation_error: "Some of what you entered needs fixing.",
  email_delivery_error: "The email could not be sent. Try again shortly.",
  http_error: "That request could not be completed.",
  internal_error: "Something went wrong at our end. Try again.",
};

/**
 * The sentence for a code.
 *
 * An unmapped code falls back to the API's own `detail` rather than to a
 * shrug: the API writes those for people, and "Something went wrong" in
 * place of a sentence that actually explained the problem is a downgrade.
 * The fallback is a gap to fill, not a design -- `SENTENCES` is what a
 * screen should be able to rely on.
 */
export function sentenceFor(code: string, detail?: string): string {
  return SENTENCES[code] ?? detail ?? "Something went wrong. Try again.";
}

/**
 * Whether this refusal means the session is gone and cannot be refreshed.
 *
 * A type predicate, so the caller that reports it does not have to widen
 * `unknown` back to an `ApiError` by hand at every catch.
 */
export function isSessionOver(error: unknown): error is ApiError {
  return (
    error instanceof ApiError &&
    (error.code === "refresh_token_reused" || error.code === "invalid_refresh_token")
  );
}

/**
 * Read a failed response into an ApiError.
 *
 * A body that is not the envelope -- a proxy's HTML error page, an empty
 * 502 -- still has to become an ApiError, because every caller above this
 * is written to expect one.
 */
export async function errorFrom(response: Response): Promise<ApiError> {
  const retryAfterHeader = response.headers.get("retry-after");
  const retryAfter = retryAfterHeader ? Number(retryAfterHeader) : null;

  let body: ErrorBody = {
    detail: response.statusText || "Request failed",
    code: "http_error",
  };

  try {
    const parsed = (await response.json()) as Partial<ErrorBody>;

    if (parsed && typeof parsed.code === "string") {
      body = {
        detail: typeof parsed.detail === "string" ? parsed.detail : body.detail,
        code: parsed.code,
        errors: parsed.errors ?? null,
      };
    }
  } catch {
    // Not JSON. The status line is all there is, and the default above
    // already says that.
  }

  return new ApiError(
    response.status,
    body,
    Number.isFinite(retryAfter) ? retryAfter : null,
  );
}
