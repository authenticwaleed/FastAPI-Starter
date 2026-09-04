"use server";

/**
 * The nine authentication endpoints, as server actions.
 *
 * Actions rather than client fetches, because the token has to land in a
 * cookie the browser cannot read and only the server can set one. A form
 * posts here, the token never enters the page, and the client bundle
 * contains no credential-handling code at all.
 *
 * Each returns a `FormState` for the form to render, or redirects. Nothing
 * here composes a sentence: `ApiError.sentence` does that, from the one map
 * in `lib/errors.ts`.
 */

import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import type { FormState } from "@/lib/form-state";
import { clearSession, readSession, writeSession, type TokenPair } from "@/lib/session";

export type { FormState };

function failure(error: unknown): FormState {
  if (error instanceof ApiError) {
    return {
      error: error.sentence,
      fields: error.fields,
      retryAfter: error.retryAfter ?? undefined,
    };
  }

  // Not a refusal -- the API was unreachable, or something threw. Say so
  // without pretending to know which.
  throw error;
}

/**
 * Where to go after signing in.
 *
 * Only a path, never an absolute URL. `?next=https://elsewhere` is an open
 * redirect, and an open redirect on a sign-in page is how a convincing
 * phishing link gets built out of a domain somebody trusts.
 */
function safeNext(value: FormDataEntryValue | null): string {
  const next = typeof value === "string" ? value : "";

  return next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

export async function signIn(_: FormState, form: FormData): Promise<FormState> {
  const destination = safeNext(form.get("next"));

  try {
    const pair = await api<TokenPair>("/auth/login", {
      method: "POST",
      anonymous: true,
      json: {
        email: form.get("email"),
        password: form.get("password"),
      },
    });

    await writeSession(pair);
  } catch (error) {
    return failure(error);
  }

  redirect(destination);
}

/**
 * Register, then sign in.
 *
 * The API answers registration with the user and no tokens, so this is two
 * calls. Signing in immediately is the right end to it: confirming an
 * address gates nothing in this API, so making somebody find an email
 * before they can see the product would be a rule this client invented.
 * The unconfirmed state is shown in the shell instead.
 */
export async function register(_: FormState, form: FormData): Promise<FormState> {
  const email = form.get("email");
  const password = form.get("password");

  try {
    await api("/auth/register", {
      method: "POST",
      anonymous: true,
      json: { email, password, name: form.get("name") },
    });

    const pair = await api<TokenPair>("/auth/login", {
      method: "POST",
      anonymous: true,
      json: { email, password },
    });

    await writeSession(pair);
  } catch (error) {
    return failure(error);
  }

  redirect("/");
}

/**
 * End this session.
 *
 * The cookies are cleared whatever the API says. A logout that failed
 * because the token was already unknown has still achieved what the person
 * asked for, and leaving them apparently signed in would be the one
 * outcome nobody wants.
 */
export async function signOut(): Promise<void> {
  const { refreshToken } = await readSession();

  if (refreshToken) {
    try {
      await api("/auth/logout", {
        method: "POST",
        anonymous: true,
        json: { refresh_token: refreshToken },
      });
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
    }
  }

  await clearSession();

  redirect("/sign-in");
}

/**
 * Ask for a reset link.
 *
 * Always reports the same thing. The API does not say whether an account
 * exists at that address, deliberately, and a screen that distinguished
 * "sent" from "no such account" would hand back exactly what the API
 * withheld.
 */
export async function forgotPassword(_: FormState, form: FormData): Promise<FormState> {
  try {
    await api("/auth/forgot-password", {
      method: "POST",
      anonymous: true,
      json: { email: form.get("email") },
    });
  } catch (error) {
    return failure(error);
  }

  return { done: true };
}

export async function resetPassword(_: FormState, form: FormData): Promise<FormState> {
  try {
    await api("/auth/reset-password", {
      method: "POST",
      anonymous: true,
      json: {
        token: form.get("token"),
        new_password: form.get("new_password"),
      },
    });
  } catch (error) {
    return failure(error);
  }

  // Not signed in afterwards: the API returns no tokens here, and resetting
  // a password ends every session there was. Signing in is the proof it
  // worked.
  redirect("/sign-in?reset=1");
}

export async function resendVerification(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  try {
    await api("/auth/resend-verification", {
      method: "POST",
      anonymous: true,
      json: { email: form.get("email") },
    });
  } catch (error) {
    return failure(error);
  }

  return { done: true };
}

/** Confirm an address from the token in an emailed link. */
export async function verifyEmail(token: string): Promise<FormState> {
  try {
    await api("/auth/verify-email", {
      method: "POST",
      anonymous: true,
      json: { token },
    });
  } catch (error) {
    return failure(error);
  }

  return { done: true };
}
