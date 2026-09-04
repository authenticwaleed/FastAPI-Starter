import Link from "next/link";
import { redirect } from "next/navigation";

import { NotificationBell } from "./notification-bell";
import { UnverifiedBanner } from "./unverified-banner";
import { WorkspaceSwitcher } from "./workspace-switcher";
import { AccountMenu } from "./account-menu";
import { api } from "@/lib/api";
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
 *
 * Nothing in this header reaches the platform console, and nothing ever
 * will: the two surfaces share components and not navigation, which is the
 * same separation the API keeps between its two routers.
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
        <div className="mx-auto flex h-14 w-full max-w-6xl items-center gap-3 px-4">
          <Link href="/" className="font-semibold tracking-tight">
            Baton
          </Link>

          <WorkspaceSwitcher />

          {/*
            Two links and no more. The inbox is what this product is for;
            everything else is reachable from the account menu or from
            inside a screen that needs it.
          */}
          <nav className="hidden items-center gap-4 text-sm sm:flex">
            <Link href="/inbox" className="hover:underline underline-offset-4">
              Inbox
            </Link>
            <Link href="/contacts" className="hover:underline underline-offset-4">
              Contacts
            </Link>
          </nav>

          <div className="ml-auto flex items-center gap-1">
            <NotificationBell />
            <AccountMenu user={user} />
          </div>
        </div>
      </header>

      {user.email_verified_at === null ? <UnverifiedBanner email={user.email} /> : null}

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">{children}</main>
    </div>
  );
}
