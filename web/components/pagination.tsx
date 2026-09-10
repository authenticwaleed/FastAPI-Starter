import Link from "next/link";

/**
 * Where you are, and the two ways out.
 *
 * Eight screens wrote this by hand and the console had a ninth of its own,
 * which is nine chances to disagree about whether the count comes before
 * the links and whether "in total" is part of the sentence.
 *
 * Links, not buttons, and no infinite scroll -- that is a rule the console
 * needs and the rest of the client may as well keep: a page fetched
 * because somebody's mouse drifted is a page nobody read, and on the
 * platform side it is also a row in the audit log saying they did.
 *
 * `as` takes the console's non-prefetching link for the same reason.
 */
export function Pagination({
  page,
  total,
  pageSize,
  href,
  noun,
  labels = { previous: "Previous", next: "Next" },
  as: Component = Link,
}: {
  page: number;
  total: number;
  pageSize: number;
  href: (page: number) => string;
  /** Plural, and named: "orders", not "results". */
  noun: string;
  /**
   * "Previous" and "Next" unless a list says otherwise. A feed ordered
   * newest-first is not going backwards when you page it, it is going
   * *older*, and calling that "next" gets it exactly the wrong way round.
   */
  labels?: { previous: string; next: string };
  as?: React.ComponentType<React.ComponentProps<typeof Link>>;
}) {
  const lastPage = Math.max(1, Math.ceil(total / pageSize));

  if (lastPage <= 1) return null;

  return (
    <nav
      aria-label="Pages"
      className="border-border-subtle flex items-center justify-between gap-4 border-t pt-3 text-sm"
    >
      <span className="text-muted-foreground tabular-nums">
        Page {page} of {lastPage} · {total.toLocaleString()} {noun}
      </span>

      <span className="flex gap-3">
        {page > 1 ? (
          <Component
            href={href(page - 1)}
            className="hover:text-foreground underline underline-offset-4"
          >
            {labels.previous}
          </Component>
        ) : null}
        {page < lastPage ? (
          <Component
            href={href(page + 1)}
            className="hover:text-foreground underline underline-offset-4"
          >
            {labels.next}
          </Component>
        ) : null}
      </span>
    </nav>
  );
}
