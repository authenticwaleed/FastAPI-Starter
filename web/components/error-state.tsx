import { cn } from "@/lib/utils";

/**
 * A screen that cannot show what it was asked for.
 *
 * Not an alert. An alert sits *within* a working screen and says something
 * about part of it; this replaces the screen, because there is nothing
 * else on it. Rendering a refusal as a toast over an empty page is how a
 * client ends up saying "something went wrong" in a corner above a blank
 * screen somebody then reloads.
 *
 * The console already had its own version of this and keeps it -- the
 * wording there is different on purpose, because a staff member reading a
 * 404 needs to be told plainly that there is no such row while a customer
 * must not be, which is the whole reason the two surfaces word refusals
 * separately. This is the shape they share.
 *
 * `code` is rendered, quietly. When somebody opens a ticket about this,
 * the stable code is the thing worth quoting; the sentence above it is not.
 */
export function ErrorState({
  title,
  children,
  code,
  action,
  tone = "critical",
  className,
  ...props
}: React.ComponentProps<"div"> & {
  title: React.ReactNode;
  /** The stable error code, where the API gave one. */
  code?: string;
  action?: React.ReactNode;
  /** `critical` for a failure; `neutral` for a refusal that is simply how
      things are -- a link that has been used, a page that is not yours. */
  tone?: "critical" | "neutral";
}) {
  return (
    <div
      role="alert"
      data-code={code}
      className={cn(
        "border-border grid gap-2 rounded-md border px-4 py-6",
        tone === "critical" && "border-destructive/25 bg-destructive/5",
        className,
      )}
      {...props}
    >
      <p
        className={cn(
          "text-sm font-medium",
          tone === "critical" && "text-destructive",
        )}
      >
        {title}
      </p>

      {children ? (
        <div className="text-muted-foreground max-w-prose text-sm">
          {children}
        </div>
      ) : null}

      {action ? <div className="mt-1">{action}</div> : null}

      {code ? (
        <p className="text-muted-foreground/80 font-mono text-2xs">{code}</p>
      ) : null}
    </div>
  );
}
