import { cn } from "@/lib/utils";

/**
 * Nothing here, and why.
 *
 * Thirty-seven places drew this themselves, all of them some spelling of
 * `rounded-md border border-dashed px-4 py-8 text-center text-sm`, and the
 * padding, the wording and whether it was a `<p>` or a `<div>` differed at
 * nearly every one.
 *
 * The dashed border is doing real work and is worth keeping: a solid box
 * containing one grey sentence reads as a row that failed to load. Dashed
 * reads as a space waiting to be filled.
 *
 * Two levels of copy, because an empty list has two things to say and they
 * are not the same sentence: *what would be here* and *what to do about
 * it*. A screen with only the first tells somebody they have arrived
 * somewhere useless; a screen with only the second does not say what it is
 * offering to do. `title` alone is fine where there is genuinely nothing to
 * do -- a filter that matched nothing.
 */
export function EmptyState({
  title,
  children,
  action,
  className,
  ...props
}: React.ComponentProps<"div"> & {
  title: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "border-border grid justify-items-center gap-1.5 rounded-md border border-dashed px-4 py-8 text-center",
        className,
      )}
      {...props}
    >
      <p className="text-sm font-medium">{title}</p>

      {children ? (
        <p className="text-muted-foreground max-w-prose text-sm text-balance">
          {children}
        </p>
      ) : null}

      {action ? <div className="mt-1.5">{action}</div> : null}
    </div>
  );
}
