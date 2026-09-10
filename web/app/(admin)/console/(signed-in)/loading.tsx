import { PageSkeleton } from "@/components/skeleton";

/**
 * The same, for the console.
 *
 * Its own file because the two surfaces do not share a layout, and a
 * boundary belongs to the segment it is in. It matters more here: these
 * screens read the platform database and several of them are slow, and a
 * support engineer who cannot tell a slow read from a dead link is one
 * who clicks again -- which on this surface is a second row in the audit
 * log for a page nobody has seen yet.
 */
export default function Loading() {
  return <PageSkeleton rows={8} />;
}
