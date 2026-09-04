import Link from "next/link";
import { redirect } from "next/navigation";

import { UnverifiedBanner } from "./unverified-banner";
import { WorkspaceSwitcher } from "./workspace-switcher";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { signOut } from "@/lib/auth-actions";
import { ApiError } from "@/lib/errors";
import type { User } from "@/lib/types";

/**
 * The signed-in shell.
 *
 * Reads the person once, here, and every screen below gets them from this
 * render rather than asking again. The proxy has already established there
 * is a session; the 401 handled below is the narrower case where it ended
 * between the proxy and this fetch -- an account deactivated, a session
 * revoked from another device -- which is rare and must still not render a
 * stack trace.
 */
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  let user: User;

  try {
    user = await api<User>("/auth/me");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) redirect("/sign-in");

    throw error;
  }

  return (
    <div className="flex min-h-svh flex-col">
      <header className="border-b">
        <div className="mx-auto flex h-14 w-full max-w-6xl items-center gap-4 px-4">
          <Link href="/" className="font-semibold tracking-tight">
            Baton
          </Link>

          <WorkspaceSwitcher />

          <div className="ml-auto flex items-center gap-3">
            <span
              className="text-muted-foreground hidden text-sm sm:inline"
              title={user.email}
            >
              {user.name}
            </span>

            {/*
              A form rather than a link. Signing out spends the refresh
              token at the API, and a GET that changes something is a GET a
              prefetcher will eventually make on somebody's behalf.
            */}
            <form action={signOut}>
              <Button type="submit" variant="ghost" size="sm">
                Sign out
              </Button>
            </form>
          </div>
        </div>
      </header>

      {user.email_verified_at === null ? <UnverifiedBanner email={user.email} /> : null}

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">{children}</main>
    </div>
  );
}
