import Link from "next/link";

/**
 * The signed-out shell.
 *
 * Its own layout because nothing in it belongs to a workspace: there is no
 * navigation, no switcher and no account menu, because there is no account
 * yet. One column, centred, and the wordmark is the only thing above the
 * card.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-8 px-4 py-12">
      <Link
        href="/"
        className="text-2xl font-semibold tracking-tight"
        aria-label="Baton"
      >
        Baton
      </Link>

      <main className="w-full max-w-sm">{children}</main>

      <p className="text-muted-foreground max-w-sm text-center text-xs text-balance">
        Customer conversations, answered by your team and helped along by an
        assistant that knows your catalogue.
      </p>
    </div>
  );
}
