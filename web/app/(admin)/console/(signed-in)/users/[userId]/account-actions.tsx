import { Act } from "@/components/console/act";
import { ConsoleLink } from "@/components/console/console-link";
import {
  activateUser,
  deactivateUser,
  revokeUserSessions,
  verifyUserEmail,
} from "@/lib/lifecycle-actions";
import type { AdminUserDetail } from "@/lib/types";

/**
 * The four things that can be done to an account.
 *
 * On the detail page rather than behind another click, unlike a
 * workspace's lifecycle: none of these destroys anything. An account
 * turned off can be turned back on, and sessions can be signed in again
 * -- so the worst outcome of a mis-click is doing it again the other way,
 * which is not worth a screen of its own.
 *
 * Each is offered only where it means something: there is no "activate"
 * on a live account and no "confirm the address" on a confirmed one. The
 * API would answer either harmlessly, and a control that does nothing is
 * a control somebody presses twice wondering why.
 */
export function AccountActions({ user }: { user: AdminUserDetail }) {
  return (
    <section className="grid gap-4">
      <div>
        <h2 className="text-sm font-medium">What can be done here</h2>
        <p className="text-muted-foreground text-xs">
          Administrator rank, all of it, and none of it destroys anything.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {user.is_active ? (
          <Act
            action={deactivateUser}
            fields={{ user_id: String(user.id) }}
            label="Turn this account off"
            variant="destructive"
            note="Signs it out everywhere, in the same breath."
            done="The account is off and its sessions have ended."
          />
        ) : (
          <Act
            action={activateUser}
            fields={{ user_id: String(user.id) }}
            label="Turn this account back on"
            note="Nothing is signed back in; they sign in again themselves."
            done="The account is on again."
          />
        )}

        <Act
          action={revokeUserSessions}
          fields={{ user_id: String(user.id) }}
          label="Sign this account out everywhere"
          note="For somebody who cannot reach their own session list."
          done="Whatever was signed in has been ended."
        />

        {user.email_verified_at === null ? (
          <Act
            action={verifyUserEmail}
            fields={{ user_id: String(user.id) }}
            label="Mark the address confirmed"
            note="When the mail will not arrive. The entry records whose word it was."
            done="The address is marked confirmed."
          />
        ) : null}

        <div className="grid gap-2">
          <p className="text-muted-foreground text-xs">
            Platform access is a different kind of act, and lives with the
            rest of it.
          </p>
          {/*
            The grant form is on the staff screen, keyed on this id. The
            API keys the grant on an account id rather than an address for
            the same reason, and a second form here would be a second
            place to keep the approval flow right.
          */}
          <ConsoleLink
            href={`/console/staff?grant=${user.id}`}
            className="w-fit text-sm underline underline-offset-4"
          >
            Give this account platform access
          </ConsoleLink>
        </div>
      </div>
    </section>
  );
}
