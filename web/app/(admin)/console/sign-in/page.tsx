import type { Metadata } from "next";

import { ConsoleSignInForm } from "./console-sign-in-form";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export const metadata: Metadata = { title: "Sign in" };

/**
 * The console's own door.
 *
 * A second sign-in for the same account, and not a mistake. §3.5: the
 * platform surface refuses a session that has been left idle while that
 * same session goes on working in the customer app, so the console keeps a
 * session of its own -- one that can end without the app noticing, which
 * is what the API asked for and what a shared pair could not give it.
 *
 * There is no "create an account" here, and there will not be one. Staff
 * are ordinary accounts that have been promoted, so whoever belongs here
 * already has a password; the API has no endpoint on this surface that
 * makes a user, deliberately.
 */
export default async function ConsoleSignInPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; expired?: string }>;
}) {
  const { next, expired } = await searchParams;

  return (
    <main className="flex flex-1 items-center justify-center px-4 py-12">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>
            <h1>Platform console</h1>
          </CardTitle>
          <CardDescription>
            For the people who run Baton, not for the businesses using it.
          </CardDescription>
        </CardHeader>

        <CardContent className="grid gap-4">
          {expired === "1" ? (
            <p
              className="bg-muted text-muted-foreground rounded-md px-3 py-2 text-sm"
              data-testid="console-expired"
            >
              The console signs out sooner than the app does. Signing in here
              again leaves whatever you have open in Baton itself alone.
            </p>
          ) : null}

          {/* Validated in the action, which is where one place decides what
              is safe to redirect to. Here it is only carried. */}
          <ConsoleSignInForm next={next ?? "/console"} />
        </CardContent>
      </Card>
    </main>
  );
}
