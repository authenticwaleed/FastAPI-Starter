import type { Metadata } from "next";

export const metadata: Metadata = {
  title: { default: "Console", template: "%s · Baton console" },
};

/**
 * The platform console's shell, which is not the application's.
 *
 * Principle 7: the two surfaces never share a layout or a nav, the same
 * separation the API keeps between its two routers. Nothing in the
 * customer app links here and nothing here links back -- a support
 * engineer with both open should never be one misread tab away from
 * answering a customer's ticket in the customer's own inbox, and the
 * plainest way to keep that true is for the two to look nothing alike.
 *
 * Hence the dark bar. It is not decoration: it is the thing that says, at
 * a glance across a desk, which of the two you are looking at.
 *
 * This layout fetches nothing. What it wraps includes the sign-in screen,
 * which by definition has no session yet, and every read on this surface
 * writes a row to the platform's audit log -- so a layout that asked the
 * API anything would spend a row on every navigation, whatever the person
 * had actually opened.
 */
export default function ConsoleShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-svh flex-col">
      <header className="bg-primary text-primary-foreground">
        <div className="mx-auto flex h-14 w-full max-w-6xl items-center gap-3 px-4">
          <span className="font-semibold tracking-tight">Baton</span>
          <span className="text-2xs tracking-widest uppercase opacity-70">
            Platform console
          </span>
        </div>
      </header>

      {children}

      {/*
        Said once, in the shell, rather than on each screen that happens to
        be sensitive. Every read here is recorded -- including the ones
        that look idle -- and somebody who knows that before they open a
        customer's account is somebody who opens the right one.
      */}
      <footer className="mx-auto w-full max-w-6xl px-4 py-6">
        <p className="text-muted-foreground border-t pt-4 text-xs">
          Everything opened here is recorded in the platform log, reads
          included.
        </p>
      </footer>
    </div>
  );
}
