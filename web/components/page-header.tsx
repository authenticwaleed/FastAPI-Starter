import Link from "next/link";

import { cn } from "@/lib/utils";

/**
 * The top of a screen, in one place instead of thirty-two.
 *
 * Every page in this client opened with the same three lines written out
 * by hand -- a `text-2xl` heading, a muted sentence, and a flex row to put
 * a search box or a button on the right -- and they had drifted: some had
 * the description, some had `mt-1` on it and some did not, and three had a
 * back link glued on with `mt-2`.
 *
 * The size came down with the move. 24px is a marketing heading; this is
 * software somebody has open for eight hours, where the title's job is to
 * say which screen this is and then get out of the way of the screen.
 */
export function PageHeader({
  title,
  description,
  back,
  meta,
  actions,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  /** A link out of here, above the title. `BackLink` renders the usual one. */
  back?: React.ReactNode;
  /** Beside the title: a status, a count -- what the title is *of*. */
  meta?: React.ReactNode;
  /** The right-hand side: search, a primary action, a filter. */
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("grid gap-1", className)}>
      {back}

      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="grid min-w-0 gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
            {meta}
          </div>

          {description ? (
            <p className="text-muted-foreground max-w-prose text-sm">
              {description}
            </p>
          ) : null}
        </div>

        {actions ? (
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {actions}
          </div>
        ) : null}
      </div>
    </div>
  );
}

/**
 * The way back, as a link rather than as browser history.
 *
 * Takes the component to render with, because the console's links are not
 * `next/link` -- they are the wrapper that turns prefetching off, and a
 * back link that prefetched would spend an audit row on a page nobody
 * opened.
 */
export function BackLink({
  href,
  label,
  as: Component = Link,
}: {
  href: string;
  label: string;
  as?: React.ComponentType<React.ComponentProps<typeof Link>>;
}) {
  return (
    <Component
      href={href}
      className="text-muted-foreground hover:text-foreground w-fit text-xs underline-offset-4 hover:underline"
    >
      ← {label}
    </Component>
  );
}

/**
 * The heading for a band within a screen.
 *
 * Fifty-nine `<h2 className="text-sm font-medium">` in the client agreed on
 * the size and disagreed on everything around it: some had a sentence under
 * them, some had a control on the right, and the gap between the heading and
 * what it headed was written five different ways.
 *
 * Deliberately small. A section heading is a signpost, not an announcement,
 * and making it large is what turns a dense operational screen into a
 * brochure with headings in it.
 */
export function SectionHeader({
  title,
  description,
  actions,
  id,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  id?: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-start justify-between gap-x-4 gap-y-1",
        className,
      )}
    >
      <div className="grid gap-0.5">
        <h2 id={id} className="text-sm font-medium">
          {title}
        </h2>
        {description ? (
          <p className="text-muted-foreground max-w-prose text-xs">
            {description}
          </p>
        ) : null}
      </div>

      {actions ? (
        <div className="flex shrink-0 items-center gap-2">{actions}</div>
      ) : null}
    </div>
  );
}

/**
 * A label over a group of facts. Smaller than a section heading, and not a
 * heading at all in the document outline -- it names a column, not a part
 * of the page.
 */
export function FieldLabel({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "text-muted-foreground text-2xs font-medium tracking-wide uppercase",
        className,
      )}
    >
      {children}
    </span>
  );
}
