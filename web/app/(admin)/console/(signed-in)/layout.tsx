import { ConsoleLink } from "@/components/console/console-link";
import { Button } from "@/components/ui/button";
import { consoleSignOut } from "@/lib/console-actions";

/**
 * The console's navigation, and the way out of it.
 *
 * Its own layout so that the sign-in screen -- a sibling of everything
 * below this -- does not carry a menu of links that would only bounce
 * somebody back to it.
 *
 * The links are not gated on rank, and that is a considered exception to
 * principle 1's "hide what a role cannot use". Knowing the rank means
 * calling `/admin/me`, and calling it here means calling it on every
 * navigation: thirty `console.opened` rows for one afternoon's visit,
 * which is the log made useless in exactly the way this phase is judged
 * on. So the platform log is listed for everybody, and support rank meets
 * a sentence there rather than a hidden door. The API is the enforcement
 * either way.
 */
export default function SignedInConsole({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <>
      <nav
        aria-label="Console"
        className="bg-muted/40 border-b"
        data-testid="console-nav"
      >
        <div className="mx-auto flex h-11 w-full max-w-6xl items-center gap-4 px-4 text-sm">
          <ConsoleLink href="/console" className="hover:underline underline-offset-4">
            Overview
          </ConsoleLink>
          <ConsoleLink
            href="/console/workspaces"
            className="hover:underline underline-offset-4"
          >
            Workspaces
          </ConsoleLink>
          <ConsoleLink
            href="/console/users"
            className="hover:underline underline-offset-4"
          >
            Accounts
          </ConsoleLink>
          <ConsoleLink
            href="/console/audit"
            className="hover:underline underline-offset-4"
          >
            Platform log
          </ConsoleLink>

          {/*
            A form rather than a link, because signing out is a thing that
            happens rather than a place to go. It ends the console session
            and only that one -- whatever is signed in to the customer app
            stays signed in, which is the whole point of the console
            keeping a session of its own.
          */}
          <form action={consoleSignOut} className="ml-auto">
            <Button type="submit" variant="ghost" size="sm">
              Sign out of the console
            </Button>
          </form>
        </div>
      </nav>

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">{children}</main>
    </>
  );
}
