import { ConsoleLink } from "@/components/console/console-link";

/**
 * Paging, as two links and a count.
 *
 * Shared across the console's four paged screens because it has to be a
 * link rather than anything cleverer: an infinite scroll would fetch the
 * next page the moment somebody's mouse drifted, and every one of those
 * fetches is a row in the platform log for a page nobody read.
 */
export function ConsolePages({
  page,
  total,
  pageSize,
  href,
  noun,
}: {
  page: number;
  total: number;
  pageSize: number;
  href: (page: number) => string;
  noun: string;
}) {
  const lastPage = Math.max(1, Math.ceil(total / pageSize));

  if (lastPage <= 1) return null;

  return (
    <nav className="flex items-center justify-between text-sm" aria-label="Pages">
      <span className="text-muted-foreground tabular-nums">
        Page {page} of {lastPage} · {total.toLocaleString()} {noun}
      </span>
      <span className="flex gap-3">
        {page > 1 ? (
          <ConsoleLink href={href(page - 1)} className="underline underline-offset-4">
            Previous
          </ConsoleLink>
        ) : null}
        {page < lastPage ? (
          <ConsoleLink href={href(page + 1)} className="underline underline-offset-4">
            Next
          </ConsoleLink>
        ) : null}
      </span>
    </nav>
  );
}
