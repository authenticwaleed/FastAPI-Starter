import type { Metadata } from "next";

import { DeleteAccount } from "./delete-account";
import { PasswordForm } from "./password-form";
import { ProfileForm } from "./profile-form";
import { SessionsList } from "./sessions-list";
import { PageHeader } from "@/components/page-header";
import { api } from "@/lib/api";
import type { Session, User } from "@/lib/types";

export const metadata: Metadata = { title: "Your account" };

/**
 * The account looking at itself.
 *
 * Outside any workspace, like the notification feed, and for the same
 * reason: none of these endpoints take a workspace, because a person has
 * one name, one password and one set of devices however many businesses
 * they work in.
 */
export default async function AccountPage() {
  const [user, sessions] = await Promise.all([
    api<User>("/auth/me"),
    api<Session[]>("/account/sessions"),
  ]);

  return (
    <div className="grid gap-8">
      <PageHeader
        title="Your account"
        description="Your details, your password, and where you are signed in."
      />

      <ProfileForm user={user} />
      <PasswordForm />
      <SessionsList sessions={sessions} />
      <DeleteAccount />
    </div>
  );
}
