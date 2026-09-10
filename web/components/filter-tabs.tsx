import Link from "next/link";

import { cn } from "@/lib/utils";

/**
 * Filters that are links, in a bar that is one line high.
 *
 * Four screens carried a private `tab()` helper returning one of two class
 * strings, and the underline it drew was the only thing saying which
 * filter was on -- which on a screen where every link is underlined is not
 * much of a signal, and for somebody who cannot see the difference between
 * two greys is none at all.
 *
 * So the current one is a filled chip and carries `aria-current`. The
 * shape changes as well as the colour, and assistive technology is told
 * outright rather than left to infer it from a font weight.
 *
 * Still links, and still a full navigation. The filter lives in the URL,
 * which is what makes "the unassigned ones" something somebody can send to
 * a colleague.
 *
 * Three pieces rather than one because the inbox needs two groups and a
 * search box on the same line, and stacking two bordered bars to get that
 * would spend a quarter of the screen saying "status" twice.
 */
export function FilterBar({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "border-border-subtle flex flex-wrap items-center gap-x-5 gap-y-2 border-y py-2",
        className,
      )}
    >
      {children}
    </div>
  );
}

export type FilterOption = {
  value: string;
  label: string;
  href: string;
  active: boolean;
  /**
   * What the filter means, where the label cannot say it. The console's
   * `past_due` list is "retrying, still entitled" -- a distinction two
   * words cannot carry and one somebody has to have before they act on
   * the list.
   */
  note?: string;
  testId?: string;
};

export function FilterGroup({
  label,
  options,
  as: Component = Link,
}: {
  /** What is being filtered on: "Status", "Who". Shown, not only read. */
  label: string;
  options: FilterOption[];
  as?: React.ComponentType<React.ComponentProps<typeof Link>>;
}) {
  return (
    <nav aria-label={label} className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <span className="text-muted-foreground text-2xs font-medium tracking-wide uppercase">
        {label}
      </span>

      <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {options.map((option) => (
          <span key={option.value} className="flex items-baseline gap-1.5">
            <Component
              href={option.href}
              aria-current={option.active ? "page" : undefined}
              data-testid={option.testId}
              className={cn(
                "rounded-md px-2 py-0.5 text-sm transition-colors",
                option.active
                  ? "bg-secondary text-secondary-foreground font-medium"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              {option.label}
            </Component>

            {option.note ? (
              <span className="text-muted-foreground text-xs">
                {option.note}
              </span>
            ) : null}
          </span>
        ))}
      </span>
    </nav>
  );
}

/** One group on its own, which is what most screens want. */
export function FilterTabs({
  label,
  options,
  as,
}: {
  label: string;
  options: FilterOption[];
  as?: React.ComponentType<React.ComponentProps<typeof Link>>;
}) {
  return (
    <FilterBar>
      <FilterGroup label={label} options={options} as={as} />
    </FilterBar>
  );
}
