import { StatusBadge } from "@/components/status-badge";
import type { MembershipStatus, WorkspaceStatus } from "@/lib/types";

/**
 * A workspace's status, toned by what it means for the business.
 *
 * Three states and three different tickets. `suspended` is an operational
 * decision the platform took and the only one that is anybody's fault, so
 * it is the only one toned as a problem. `cancelled` is a business that
 * closed itself: ordinary, and the row that matters most on this surface,
 * because it is the one with a date on it -- so it is quiet rather than
 * absent.
 */
export function WorkspaceStatusBadge({ status }: { status: WorkspaceStatus }) {
  return (
    <StatusBadge
      tone={
        status === "suspended"
          ? "critical"
          : status === "cancelled"
            ? "quiet"
            : "neutral"
      }
      status={status}
    >
      {status}
    </StatusBadge>
  );
}

/** Whether somebody is on a team, was invited to one, or has left it. */
export function MembershipStatusBadge({ status }: { status: MembershipStatus }) {
  return (
    <StatusBadge
      tone={status === "active" ? "neutral" : "quiet"}
      status={status}
    >
      {status}
    </StatusBadge>
  );
}
