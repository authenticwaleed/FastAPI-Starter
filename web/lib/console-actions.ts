"use server";

/**
 * The four things the console does that are not reads.
 *
 * Two are about getting into it and back out: both call `/auth/*`, the
 * ordinary tenant login every account uses, because staff are ordinary
 * accounts that have been promoted. What the console has of its own is a
 * *session*, not an identity. Nothing here reads or writes the tenant
 * cookies -- §3.5 again: signing in to the console must not disturb the
 * app, and signing out of it must not sign somebody out of their own
 * inbox.
 *
 * The other two ask for a window on a customer's data and close it. They
 * change a grant on the platform's own side and write nothing into
 * anybody's workspace; the whole of this surface is still read-only where
 * a customer is concerned.
 */

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import { adminApi } from "@/lib/console-api";
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
import {
  forgetSupportWindow,
  rememberSupportWindow,
} from "@/lib/support-window";
import type { SupportGrant } from "@/lib/types";

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

/** The shape every refusal on this surface hands back to a form. */
function failure(error: unknown): FormState {
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
    return failure(error);
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

// --- support access (W11) ---------------------------------------------

/**
 * Where a workspace's console screens live, for revalidating them.
 *
 * Requesting or ending access changes what three screens show -- the
 * support-access page itself, and the two that are refused without a live
 * grant -- so all three are dropped rather than only the one the form was
 * standing on.
 */
function workspaceScreens(workspaceId: string): string[] {
  const base = `/console/workspaces/${workspaceId}`;

  return [`${base}/support-access`, `${base}/conversations`, base];
}

/**
 * Ask for a time-boxed window on one customer's data.
 *
 * Nothing about this is quiet, and the form that calls it says so before
 * anybody types: the grant is written down, the customer sees it in their
 * own audit log with the reason given here, and every read it later
 * permits is recorded separately.
 *
 * The expiry the API returns is kept in a cookie, because it is the only
 * time a support engineer is ever told it -- listing grants is
 * administrator rank. See `lib/support-window.ts` for why that is a
 * memory rather than a permission.
 */
export async function requestSupportAccess(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const hours = form.get("hours");

  try {
    const grant = await adminApi<SupportGrant>(
      `/workspaces/${workspaceId}/support-access`,
      {
        method: "POST",
        json: {
          reason: form.get("reason"),
          // Omitted rather than sent empty, so the API's own default --
          // four hours, which is a shift -- applies when nobody chose.
          ...(hours ? { hours: Number(hours) } : {}),
        },
      },
    );

    await rememberSupportWindow(workspaceId, grant.expires_at);
  } catch (error) {
    return failure(error);
  }

  for (const path of workspaceScreens(workspaceId)) revalidatePath(path);

  return { done: true };
}

/**
 * Close your own window before it runs out.
 *
 * The API answers 204 whether there was a live grant or not: ending
 * access you no longer hold is not an error, and somebody closing a
 * window they have finished with should not have to know whether it had
 * already expired. So this reports no failure of its own either, and the
 * remembered expiry goes whatever happened -- which is the state the
 * person asked for.
 */
export async function endSupportAccess(form: FormData): Promise<void> {
  const workspaceId = String(form.get("workspace_id") ?? "");

  try {
    await adminApi<void>(`/workspaces/${workspaceId}/support-access`, {
      method: "DELETE",
    });
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
  }

  await forgetSupportWindow(workspaceId);

  for (const path of workspaceScreens(workspaceId)) revalidatePath(path);
}
