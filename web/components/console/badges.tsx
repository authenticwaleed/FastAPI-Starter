import { Badge } from "@/components/ui/badge";
import type { MembershipStatus, WorkspaceStatus } from "@/lib/types";

/**
 * A workspace's status, coloured by what it means for the business.
 *
 * Three states and three different tickets. `suspended` is an operational
 * decision the platform took and the only one that is anybody's fault, so
 * it is the only one coloured as a problem. `cancelled` is a business that
 * closed itself: ordinary, and the row that matters most on this surface,
 * because it is the one with a date on it.
 */
export function WorkspaceStatusBadge({ status }: { status: WorkspaceStatus }) {
  return (
    <Badge
      variant={
        status === "suspended"
          ? "destructive"
          : status === "cancelled"
            ? "outline"
            : "secondary"
      }
      data-status={status}
    >
      {status}
    </Badge>
  );
}

/** Whether somebody is on a team, was invited to one, or has left it. */
export function MembershipStatusBadge({ status }: { status: MembershipStatus }) {
  return (
    <Badge variant={status === "active" ? "secondary" : "outline"} data-status={status}>
      {status}
    </Badge>
  );
}
