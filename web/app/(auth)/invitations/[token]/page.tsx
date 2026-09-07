import type { Metadata } from "next";
import Link from "next/link";

import { AcceptInvitation } from "./accept-invitation";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ApiError, sentenceFor } from "@/lib/errors";
import { readSession } from "@/lib/session";
import { ROLE_DESCRIPTION } from "@/lib/roles";
import { previewInvitation } from "@/lib/team";
import type { InvitationPreview } from "@/lib/types";

export const metadata: Metadata = { title: "You have been invited" };

/**
 * What the link says, before anybody commits to anything.
 *
 * In the signed-out shell rather than the app's, because whoever is
 * reading it may not have an account yet -- which is the point of having
 * been invited. It renders the same either way; the proxy lets this path
 * through with or without a session, unlike the sign-in page.
 *
 * The preview carries nothing that would matter to whoever else got hold
 * of the link. The token is the only credential involved, and accepting
 * still requires being signed in as the address it names.
 */
export default async function InvitationPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;

  let invitation: InvitationPreview;

  try {
    invitation = await previewInvitation(token);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;

    return (
      <Card>
        <CardHeader>
          <CardTitle>
            <h1>This link does not work</h1>
          </CardTitle>
          <CardDescription>{sentenceFor(error.code, error.detail)}</CardDescription>
        </CardHeader>
        <CardFooter>
          <Link href="/sign-in" className="text-sm underline underline-offset-4">
            Sign in
          </Link>
        </CardFooter>
      </Card>
    );
  }

  const { accessToken } = await readSession();
  const signedIn = accessToken !== null;

  if (invitation.status !== "pending") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>
            <h1>
              {invitation.status === "accepted"
                ? "Already accepted"
                : "This invitation has expired"}
            </h1>
          </CardTitle>
          <CardDescription>
            {invitation.status === "accepted"
              ? `Somebody has already used this link to join ${invitation.workspace_name}.`
              : // A 410 rather than a 404 at the API, and this is the
                // difference in words: the link was real, so the answer is
                // "ask for another" rather than "check the address".
                `Ask somebody in ${invitation.workspace_name} to send another.`}
          </CardDescription>
        </CardHeader>
        <CardFooter>
          <Link href={signedIn ? "/" : "/sign-in"} className="text-sm underline underline-offset-4">
            {signedIn ? "Go to Baton" : "Sign in"}
          </Link>
        </CardFooter>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h1>Join {invitation.workspace_name}</h1>
        </CardTitle>
        <CardDescription>
          You have been invited as <strong>{invitation.role}</strong> —{" "}
          {ROLE_DESCRIPTION[invitation.role].toLowerCase()}
        </CardDescription>
      </CardHeader>

      <CardContent className="grid gap-4">
        <p className="text-muted-foreground text-sm">
          This invitation admits <strong>{invitation.email}</strong> and no
          other address.
        </p>

        {signedIn ? (
          <AcceptInvitation token={token} />
        ) : (
          <div className="grid gap-2">
            <p className="text-muted-foreground text-sm">
              Sign in as that address to accept, or create the account first.
            </p>
            <div className="flex flex-wrap gap-3 text-sm">
              <Link
                href={`/sign-in?next=${encodeURIComponent(`/invitations/${token}`)}`}
                className="underline underline-offset-4"
              >
                Sign in
              </Link>
              <Link
                href="/register"
                className="text-muted-foreground underline-offset-4 hover:underline"
              >
                Create an account
              </Link>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
