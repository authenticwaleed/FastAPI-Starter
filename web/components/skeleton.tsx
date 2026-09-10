import { cn } from "@/lib/utils";

/**
 * The shape of what is coming.
 *
 * This client had no loading state at all -- no `loading.tsx`, no
 * `Suspense`, no spinner. Every screen is a server component awaiting the
 * API, so a navigation simply did nothing until the next page arrived, and
 * on a slow connection "did nothing" is indistinguishable from "the link
 * is broken".
 *
 * A skeleton rather than a spinner, because a spinner says only *wait* and
 * these say *wait, and it will look like this* -- which is the difference
 * between a screen that feels slow and one that feels like it is loading.
 *
 * `animate-pulse` and nothing else. The reduced-motion rule in the base
 * layer stops it for anybody who asked, and what remains is still a
 * legible outline.
 */
export function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      aria-hidden="true"
      className={cn("bg-muted animate-pulse rounded-md", className)}
      {...props}
    />
  );
}

/** A row in a list: a title, a line under it, and something on the right. */
export function SkeletonRow() {
  return (
    <div className="row flex items-center gap-3">
      <div className="grid min-w-0 flex-1 gap-1.5">
        <Skeleton className="h-3.5 w-40 max-w-[45%]" />
        <Skeleton className="h-3 w-64 max-w-[70%]" />
      </div>
      <Skeleton className="h-5 w-16 shrink-0" />
    </div>
  );
}

export function SkeletonRows({ rows = 6 }: { rows?: number }) {
  return (
    <div className="grid gap-2">
      {Array.from({ length: rows }, (_, index) => (
        <SkeletonRow key={index} />
      ))}
    </div>
  );
}

/**
 * A whole screen: the header, then a list.
 *
 * Deliberately generic. It stands in for every route in a segment, so it
 * has to be the shape they share rather than the shape of any one of them
 * -- a skeleton that promises a table and resolves into a form is worse
 * than no skeleton.
 *
 * `role="status"` with a name, so this is announced as "loading" rather
 * than as a screenful of unlabelled boxes.
 */
export function PageSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="grid gap-6" role="status" aria-label="Loading">
      <div className="grid gap-2">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-3.5 w-72 max-w-full" />
      </div>

      <SkeletonRows rows={rows} />
    </div>
  );
}
