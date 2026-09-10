import { PageSkeleton } from "@/components/skeleton";

/**
 * What every screen in the customer app shows while it is being fetched.
 *
 * One file, at the top of the segment, rather than one per route. Next
 * wraps this segment's children in a boundary and every screen below
 * inherits it, so a navigation paints the shell and the header
 * immediately and fills the middle in when the API answers.
 *
 * Before this there was nothing at all -- no `loading.tsx`, no
 * `Suspense`, no spinner anywhere in the client. Every screen is a server
 * component awaiting the API, so clicking a link did nothing visible
 * until the next page arrived, and on a slow connection "nothing
 * visible" is indistinguishable from a broken link.
 *
 * Generic on purpose: it stands in for a table, a form and an inbox, so
 * it has to be the shape they share. A skeleton promising a table that
 * resolves into a form is worse than no skeleton.
 */
export default function Loading() {
  return <PageSkeleton />;
}
