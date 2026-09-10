import type { Metadata } from "next";

import { GrantAccess } from "./grant-access";
import { StaffRow } from "./staff-row";
import { ConsoleLink } from "@/components/console/console-link";
import { ConsoleHeading } from "@/components/console/heading";
import { consoleRefusal } from "@/components/console/refusal";
import { SectionHeader } from "@/components/page-header";
import { approvalsFor, pendingApproval, usableApproval } from "@/lib/approvals";
import { listStaff, whoami } from "@/lib/console";
import type { Approval, StaffMember } from "@/lib/types";

export const metadata: Metadata = { title: "Staff" };

/**
 * Everybody who runs this platform, and the one screen that can change it.
 *
 * Two reads, and the second one earns its place. `/admin/staff` is the
 * list; `/admin/me` is how this screen knows which row is the reader's
 * own, and that is not decoration — revoking your own access, or demoting
 * yourself out of the rank that grants it, locks you out of the console
 * with nobody but a colleague able to let you back in. The row says so
 * instead of offering the controls.
 *
 * That is this client's caution rather than the API's rule: the API
 * refuses only when you are the *last* owner, and it is right to, because
 * a platform with no live owner is a console nobody can be added to again.
 * So the sentence on your own row talks about consequence, not permission.
 *
 * The approval list is read only when somebody is part-way through
 * granting an owner — `?grant=` in the address — because every read here
 * is a row in the platform log, and the ordinary visit to this screen is
 * somebody checking who has access.
 */
export default async function ConsoleStaffPage({
  searchParams,
}: {
  searchParams: Promise<{ grant?: string }>;
}) {
  const { grant } = await searchParams;

  let staff: StaffMember[];
  let me: StaffMember;

  try {
    [staff, me] = await Promise.all([listStaff(), whoami()]);
  } catch (error) {
    return consoleRefusal(error, {
      title: "Staff",
      missing: "No such staff member.",
    });
  }

  // Only for the account being granted to, and only while one is being
  // granted. An owner promotion needs a colleague's agreement; the other
  // two ranks are ordinary promotions that one person decides.
  let approvals: Approval[] = [];

  if (grant) approvals = await approvalsFor("grant_staff_owner", grant);

  /**
   * Above the list when somebody arrived here to use it.
   *
   * They followed "give this account platform access" from an account, and
   * a screen that answers that with a page of colleagues to scroll past is
   * one that loses the thing it was opened for.
   */
  const granting = (
    <section className="grid gap-4">
      <div>
        <SectionHeader title="Give somebody access" />
        <p className="text-muted-foreground text-xs">
          Staff are ordinary accounts that have been promoted, so whoever
          belongs here has registered already. Find them under{" "}
          <ConsoleLink href="/console/users" className="underline underline-offset-4">
            Accounts
          </ConsoleLink>{" "}
          and come back from there — this is keyed on an account id, as the
          API is.
        </p>
      </div>

      <GrantAccess
        userId={grant ?? null}
        ready={usableApproval(approvals)}
        waiting={pendingApproval(approvals)}
      />
    </section>
  );

  const live = staff.filter((member) => member.revoked_at === null);
  const gone = staff.filter((member) => member.revoked_at !== null);
  const owners = live.filter((member) => member.role === "owner").length;

  return (
    <div className="grid gap-8">
      <ConsoleHeading
        title="Staff"
        description="The people who run Baton itself, not the businesses using it. Granting and revoking is an owner's to do; everything else here is an administrator's to read."
      />

      {grant ? granting : null}

      <section className="grid gap-3">
        <div>
          <SectionHeader title="With access" />
          <p className="text-muted-foreground text-xs">
            A ladder rather than a set: everything support may do, an
            administrator may do too. {owners} owner{owners === 1 ? "" : "s"},
            and the platform has to keep at least one.
          </p>
        </div>

        <ul className="grid gap-2" data-testid="staff-list">
          {live.map((member) => (
            <StaffRow
              key={member.user_id}
              member={member}
              yours={member.user_id === me.user_id}
              lastOwner={member.role === "owner" && owners <= 1}
            />
          ))}
        </ul>
      </section>

      {grant ? null : granting}

      {gone.length > 0 ? (
        <section className="grid gap-3">
          <SectionHeader
            title="Access taken away"
            description="Kept, because this is the half of the screen somebody needs after an incident: who used to have this, and when it stopped."
          />

          <ul className="grid gap-2" data-testid="revoked-staff">
            {gone.map((member) => (
              <StaffRow key={member.user_id} member={member} yours={false} />
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
