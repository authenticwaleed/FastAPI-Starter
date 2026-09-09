import type { Metadata } from "next";

import { ConsoleLink } from "@/components/console/console-link";
import { Facts, Fact } from "@/components/console/facts";
import { ConsoleHeading } from "@/components/console/heading";
import { consoleRefusal } from "@/components/console/refusal";
import { Badge } from "@/components/ui/badge";
import { whoami } from "@/lib/console";
import { STAFF_ROLE_LABEL, STAFF_ROLE_REACH, when } from "@/lib/console-labels";
import type { StaffMember } from "@/lib/types";

export const metadata: Metadata = { title: "Overview" };

/** The three places to start from, and nothing loaded on their behalf. */
const SECTIONS = [
  {
    href: "/console/workspaces",
    title: "Workspaces",
    body: "Find a business by name, by address, or by the address of anyone in it. Closed ones are here too, with the date their records go.",
  },
  {
    href: "/console/users",
    title: "Accounts",
    body: "Find a person. Where they belong, whether their account is live, and whether anything is signed in.",
  },
  {
    href: "/console/staff",
    title: "Staff",
    body: "Who runs this platform. Administrators read it; only an owner changes it.",
  },
  {
    href: "/console/audit",
    title: "Platform log",
    body: "What staff have done, reads included. Administrators and above.",
  },
];

/**
 * Who you are on this platform.
 *
 * The one screen that calls `/admin/me`, and so the one that writes
 * `console.opened`. That row is what lets the log answer "who was in the
 * console on Tuesday afternoon" about a visit where nothing else was
 * opened -- which is why it belongs to the front door and not to the
 * layout, where every navigation would claim to be another arrival.
 *
 * The three cards below are links and nothing else. Not one of them
 * carries a count, a preview or a "recently viewed", because every one of
 * those would be a read of somebody's account that nobody asked for.
 */
export default async function ConsolePage() {
  let me: StaffMember;

  try {
    me = await whoami();
  } catch (error) {
    // `not_staff` lands here: an ordinary account that signed in at the
    // console door. It is terminal and says so -- there is nothing to
    // click, because nothing this person does to this screen changes the
    // answer.
    return consoleRefusal(error, {
      title: "Platform console",
      missing: "No such staff member.",
    });
  }

  return (
    <div className="grid gap-8">
      <ConsoleHeading
        title={me.name}
        description="You are signed in to the platform console. Your session in Baton itself is separate, and untouched."
      />

      <section className="grid gap-3">
        <Facts>
          <Fact label="Account">{me.email}</Fact>
          <Fact label="Rank">
            <span className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary" data-testid="staff-role">
                {STAFF_ROLE_LABEL[me.role]}
              </Badge>
              <span className="text-muted-foreground text-xs">
                {STAFF_ROLE_REACH[me.role]}
              </span>
            </span>
          </Fact>
          <Fact label="Granted">{when(me.granted_at)}</Fact>
        </Facts>
      </section>

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {SECTIONS.map((section) => (
          <ConsoleLink
            key={section.href}
            href={section.href}
            className="hover:bg-accent/50 grid content-start gap-1 rounded-md border px-4 py-3"
          >
            <span className="text-sm font-medium">{section.title}</span>
            <span className="text-muted-foreground text-xs">{section.body}</span>
          </ConsoleLink>
        ))}
      </section>
    </div>
  );
}
