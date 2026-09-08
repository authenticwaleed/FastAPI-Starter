"use server";

/**
 * Getting into the console, and back out of it.
 *
 * The only two things on this surface that are not reads, and neither of
 * them touches the platform: both call `/auth/*`, which is the ordinary
 * tenant login every account uses. Staff are ordinary accounts that have
 * been promoted, so there is no second password and no second directory --
 * what the console has of its own is a *session*, not an identity.
 *
 * Nothing here reads or writes the tenant cookies. That is the whole point
 * of §3.5: signing in to the console must not disturb the app, and signing
 * out of the console must not sign somebody out of their own inbox.
 */

import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import {
  CONSOLE_PATH,
  CONSOLE_SIGN_IN_PATH,
  clearConsoleSession,
  readConsoleSession,
  writeConsoleSession,
} from "@/lib/console-session";
import { ApiError } from "@/lib/errors";
import type { FormState } from "@/lib/form-state";
import type { TokenPair } from "@/lib/session";

export type { FormState };

/**
 * Where to go after signing in, and it had better be the console.
 *
 * The tenant sign-in only insists on a path, because any path is a page
 * that person may see. This one insists on `/console` as well: the console
 * session is not the app's, so finishing a console sign-in anywhere else
 * would land somebody on a screen their console cookies say nothing about.
 */
function safeNext(value: FormDataEntryValue | null): string {
  const next = typeof value === "string" ? value : "";

  return next === CONSOLE_PATH || next.startsWith(`${CONSOLE_PATH}/`)
    ? next
    : CONSOLE_PATH;
}

export async function consoleSignIn(_: FormState, form: FormData): Promise<FormState> {
  const destination = safeNext(form.get("next"));

  try {
    const pair = await api<TokenPair>("/auth/login", {
      method: "POST",
      anonymous: true,
      json: { email: form.get("email"), password: form.get("password") },
    });

    // Written without asking the platform anything first. Whether this
    // account is staff is `/admin/me`'s answer, and the console's front
    // page asks it -- one call, on the screen that was opened, rather than
    // a second one here that nobody requested.
    await writeConsoleSession(pair);
  } catch (error) {
    if (error instanceof ApiError) {
      return {
        error: error.sentence,
        code: error.code,
        fields: error.fields,
        retryAfter: error.retryAfter ?? undefined,
      };
    }

    throw error;
  }

  redirect(destination);
}

/**
 * End the console session, and only that one.
 *
 * The cookies go whatever the API says, like the tenant sign-out: a logout
 * refused because the token was already unknown has still achieved what
 * was asked, and leaving somebody apparently signed in is the one outcome
 * nobody wants.
 */
export async function consoleSignOut(): Promise<void> {
  const { refreshToken } = await readConsoleSession();

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

  await clearConsoleSession();

  redirect(CONSOLE_SIGN_IN_PATH);
}
