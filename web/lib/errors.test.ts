import { describe, expect, it } from "vitest";

import {
  ApiError,
  SENTENCES,
  errorFrom,
  isSessionOver,
  sentenceFor,
} from "@/lib/errors";

/**
 * The refusal renderer, which is the thing every screen leans on.
 *
 * These are the failures that would otherwise be found by reading a raw
 * JSON body on a login page.
 */

describe("sentenceFor", () => {
  it("has a sentence for every code W1's endpoints can return", () => {
    // Taken from app/api/errors.py, for the nine auth routes and the
    // refusals any request can meet. A code the API can return and this
    // map cannot render is a screen showing the API's prose.
    const reachable = [
      "invalid_credentials",
      "inactive_user",
      "incorrect_password",
      "email_already_exists",
      "user_not_found",
      "invalid_refresh_token",
      "refresh_token_reused",
      "session_not_found",
      "invalid_verification_token",
      "rate_limit_exceeded",
      "validation_error",
      "email_delivery_error",
      "http_error",
      "internal_error",
    ];

    const missing = reachable.filter((code) => !(code in SENTENCES));

    expect(missing).toEqual([]);
  });

  it("falls back to the API's own prose for a code it does not know", () => {
    expect(sentenceFor("some_code_from_a_later_phase", "The shop said no")).toBe(
      "The shop said no",
    );
  });

  it("still says something when there is no prose either", () => {
    expect(sentenceFor("unknown")).toBeTruthy();
  });

  it("does not leak the API's wording for a code it does know", () => {
    // The whole point of the map: `detail` may be reworded upstream, and a
    // screen that showed it would change wording with an API deploy.
    expect(sentenceFor("invalid_credentials", "Incorrect email or password")).toBe(
      SENTENCES.invalid_credentials,
    );
  });
});

describe("ApiError", () => {
  it("keys field errors by the last element of loc, ready for an input", () => {
    const error = new ApiError(422, {
      detail: "Request validation failed",
      code: "validation_error",
      errors: [
        { loc: ["body", "email"], msg: "not an email" },
        { loc: ["body", "password"], msg: "too short" },
      ],
    });

    expect(error.fields).toEqual({ email: "not an email", password: "too short" });
  });

  it("keeps the first message when a field has several", () => {
    const error = new ApiError(422, {
      detail: "Request validation failed",
      code: "validation_error",
      errors: [
        { loc: ["body", "password"], msg: "too short" },
        { loc: ["body", "password"], msg: "needs a digit" },
      ],
    });

    expect(error.fields.password).toBe("too short");
  });

  it("has no fields when nothing was a validation failure", () => {
    const error = new ApiError(401, {
      detail: "Not authenticated",
      code: "invalid_credentials",
    });

    expect(error.fields).toEqual({});
  });
});

describe("isSessionOver", () => {
  it("is true for a replayed refresh token", () => {
    const error = new ApiError(401, {
      detail: "…",
      code: "refresh_token_reused",
    });

    expect(isSessionOver(error)).toBe(true);
  });

  it("is false for the API being unreachable", () => {
    // The distinction that stops an outage signing everybody out.
    expect(isSessionOver(new TypeError("fetch failed"))).toBe(false);
  });

  it("is false for an ordinary refusal", () => {
    const error = new ApiError(403, { detail: "…", code: "inactive_user" });

    expect(isSessionOver(error)).toBe(false);
  });
});

describe("errorFrom", () => {
  it("reads the envelope", async () => {
    const response = new Response(
      JSON.stringify({ detail: "Your plan does not include this", code: "feature_not_in_plan" }),
      { status: 402, headers: { "content-type": "application/json" } },
    );

    const error = await errorFrom(response);

    expect(error.status).toBe(402);
    expect(error.code).toBe("feature_not_in_plan");
  });

  it("survives a body that is not the envelope", async () => {
    // A proxy's HTML error page, or an empty 502. Every caller above this
    // is written to expect an ApiError, so one has to come back.
    const response = new Response("<html>502 Bad Gateway</html>", { status: 502 });

    const error = await errorFrom(response);

    expect(error.status).toBe(502);
    expect(error.code).toBe("http_error");
    expect(error.sentence).toBeTruthy();
  });

  it("carries Retry-After off a 429", async () => {
    const response = new Response(
      JSON.stringify({ detail: "Too many", code: "rate_limit_exceeded" }),
      { status: 429, headers: { "content-type": "application/json", "retry-after": "42" } },
    );

    expect((await errorFrom(response)).retryAfter).toBe(42);
  });
});
