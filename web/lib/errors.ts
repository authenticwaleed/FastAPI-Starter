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

  // --- the team, and its invitations (W4) ---------------------------------
  //
  // `invitation_expired` is a 410 rather than a 404, and the difference is
  // the whole message: the link was real, so the answer is "ask for
  // another" rather than "check the address".
  invitation_not_found: "That invitation link is not one we know.",
  invitation_expired: "This invitation has expired. Ask for another.",
  invitation_already_accepted: "This invitation has already been used.",
  invitation_not_yours: "This invitation was sent to a different address.",
  invitation_already_pending: "That address has already been invited.",
  already_a_member: "That person is already in this workspace.",

  // --- the inbox (W3) -----------------------------------------------------
  //
  // Two of these are not faults. Two people working one inbox will race
  // each other, and a thread somebody else closed a second ago is an
  // ordinary outcome of that rather than something to colour red.
  conversation_not_found: "That conversation is no longer here.",
  conversation_closed: "This conversation was closed. Reopen it to reply.",
  conversation_already_open: "That contact already has an open conversation.",
  contact_not_found: "That contact is no longer here.",
  contact_already_exists: "A contact with that number already exists.",
  message_not_found: "That message is no longer here.",

  // --- the knowledge base (W5) --------------------------------------------
  //
  // The two upload refusals mean different things and must not share a
  // sentence: 415 is a file we cannot open at all, 422 is one we opened
  // and found no text in. The second is the ordinary fate of a scan, and
  // "it failed" would send somebody hunting for a bug rather than for a
  // different file.
  knowledge_source_not_found: "That source is no longer here.",
  knowledge_document_not_found: "That document is no longer here.",
  unsupported_document_type: "Only PDFs and plain text files can be added.",
  unreadable_document: "No text could be read from that file.",
  // Not a failure. The same content is already in the knowledge base, so
  // the state somebody wanted already holds.
  document_already_ingested: "This is already in your knowledge base.",

  // --- automations and integrations (W8) ----------------------------------
  automation_not_found: "That automation is no longer here.",
  automation_already_exists: "That automation is already set up here.",
  // 422 rather than 400: the request was well formed and what was inside
  // it did not fit the automation it named -- which is what tells somebody
  // to fix the form rather than the call.
  invalid_automation_settings: "Those settings are not valid for this automation.",
  whatsapp_not_connected: "No WhatsApp number is connected to this workspace.",
  whatsapp_already_connected: "A WhatsApp number is already connected.",
  storefront_not_connected: "No storefront is connected to this workspace.",
  storefront_already_connected: "A storefront is already connected.",
  ecommerce_provider_error:
    "The shop could not be reached, or it refused the connection.",
  // 503, and about this deployment rather than the person: a provider
  // credential cannot be encrypted because no encryption key is
  // configured. Nothing they type will fix it, so the sentence does not
  // suggest trying again differently.
  integration_unavailable:
    "Connections are not available on this deployment. Ask whoever runs it.",

  // --- analytics, audit and API keys (W9) ---------------------------------
  //
  // Both 422s belong on the range picker rather than the page: the
  // request was well formed and a value in it was not, which is what
  // tells somebody to change the dates rather than the call.
  api_key_not_found: "That key is no longer here.",
  invalid_date_range: "That range is backwards, or longer than allowed.",
  unknown_timezone: "That is not a timezone we recognise.",

  // --- the catalogue and its orders (W6) ----------------------------------
  //
  // Both conflicts belong on a field rather than on the page. A SKU
  // already in use is one input to change; an order that is no longer
  // pending is somebody else having moved first.
  product_not_found: "That product is no longer here.",
  product_conflict: "That SKU or external id is already used in this workspace.",
  order_not_found: "That order is no longer here.",
  order_already_exists: "An order with that external id already exists.",
  order_not_confirmable:
    "This order is not pending any more, so it cannot be confirmed.",

  // --- the platform console (W10) ------------------------------------------
  //
  // Every one of these is answered honestly by the API, unlike the tenant
  // refusals above, and it can afford to be: nobody reaches an /admin
  // route without a session already matched to a live staff row, so there
  // is no stranger here to keep in the dark.
  //
  // All three are terminal. Nothing the person types, and no form they
  // change, turns any of them into a yes, so the wording offers nothing to
  // try -- a "try again" under a refusal that cannot be retried is worse
  // than silence.
  not_staff: "This account does not have access to the platform console.",
  insufficient_staff_role: "Your staff role does not include this.",
  // An IP allowlist, and a console-only refusal with no tenant equivalent.
  address_not_allowed: "The console does not accept connections from this address.",
  // 401, and the one refusal on this surface that signing in again fixes.
  // Deliberately says what it is about: the console keeps a shorter clock
  // than the app, and somebody who has just been using the app without
  // trouble will otherwise read this as a fault.
  admin_session_expired:
    "The console signs out sooner than the app does. Sign in again to carry on.",

  // --- support access (W11) ------------------------------------------------
  //
  // The first of these is the refusal the whole phase is built around, and
  // the wording is the phase's own rule: it must read as "ask for access"
  // rather than as a fault. It covers a grant that never existed, one that
  // expired and one that was revoked -- unusual on a surface where
  // everything else is exact, and right, because all three mean the same
  // thing to the person asking and lead to the same next step.
  support_access_required:
    "You do not have a live window on this account. Ask for one, with a reason.",
  support_access_already_granted:
    "You already have a live window on this account.",
  // 422, and the one sentence here that cannot say what the plan asks it
  // to. The maximum is configured per deployment and the API returns it in
  // neither the response nor the schema, so naming the number would be the
  // client inventing a fact -- §7's third refusal. Saying which way to go
  // is the honest half of it; an endpoint that answers "how long may I
  // ask for" is the other, and it belongs in the API's plan.
  support_grant_too_long:
    "That is longer than this deployment allows. Ask for fewer hours.",

  // --- lifecycle, and the people who run it (W12) --------------------------
  //
  // Two of these carry their own particulars in `detail` -- which state
  // refused this, which colleague already approved it -- and the screens
  // show that line beneath the sentence. Showing `detail` is not branching
  // on it: nothing anywhere decides anything from those words, and the
  // code is still what a screen reads.
  workspace_lifecycle: "That is not possible from where this workspace is.",
  confirmation_mismatch: "That is not this workspace's address. Check what you typed.",
  // 403, and neither an error nor a retry: it means find a colleague.
  approval_required: "This needs a second staff member to agree to it.",
  staff_member_not_found: "No account with that id, or it has never had access.",
  already_staff: "That account already has platform access.",
  last_staff_owner: "The platform has to keep at least one owner.",

  // --- the plan getting in the way ----------------------------------------
  //
  // 402, not 403. A 403 says "you may not", which sends somebody to an
  // administrator who cannot help; these say the plan is what is in the
  // way, and the plan is something they can change themselves.
  feature_not_in_plan: "Your plan does not include this.",
  plan_limit_reached: "You have used everything your plan allows this month.",

  // --- something we depend on, rather than something you did --------------
  billing_provider_error:
    "The payment provider could not be reached. Nothing was charged — try again shortly.",
  reply_provider_error: "The assistant could not be reached. Try again shortly.",
  messaging_provider_error: "WhatsApp could not be reached. Try again shortly.",
  // Reached from adding a document as well as from searching -- both go
  // through the same provider -- so the wording cannot say "search".
  embedding_provider_error:
    "The knowledge service is unavailable right now. Try again shortly.",

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
