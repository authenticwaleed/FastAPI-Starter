/**
 * One request to the platform surface, on the console's own session.
 *
 * Its own module because two callers need it now: the reads in
 * `lib/console.ts`, and the two acts in `lib/console-actions.ts` that ask
 * for support access and end it. One place attaches the console's bearer
 * and answers a 401, so a screen cannot accidentally reach `/admin` with
 * the tenant session or sign somebody out of the app by trying.
 */

import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import { CONSOLE_SIGN_IN_PATH, readConsoleSession } from "@/lib/console-session";
import { ApiError } from "@/lib/errors";

type Options = { method?: string; json?: unknown };

/**
 * The 401 is caught here rather than by each screen because there is one
 * right answer to it and it is the same everywhere: the console signs out
 * on its own schedule (§3.5), and what that needs is the console's sign-in
 * screen. It does not need -- and must not have -- the tenant session
 * cleared, which is why nothing in this file touches those cookies.
 *
 * `403`, `404` and the conflicts are left to the caller. Each means
 * something on this surface that it does not mean on the other, and the
 * screen is where that gets said.
 */
export async function adminApi<T>(path: string, options: Options = {}): Promise<T> {
  const { accessToken } = await readConsoleSession();

  if (!accessToken) redirect(CONSOLE_SIGN_IN_PATH);

  try {
    return await api<T>(`/admin${path}`, { ...options, bearer: accessToken });
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      redirect(`${CONSOLE_SIGN_IN_PATH}?expired=1`);
    }

    throw error;
  }
}
