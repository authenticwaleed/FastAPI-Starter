import { ConsoleLink } from "@/components/console/console-link";

/** What the API allows, and what it defaults to. */
const WINDOWS = [7, 30, 90, 365];
const DEFAULT_DAYS = 30;

/**
 * How far back a chart looks, from the address.
 *
 * Links rather than a form, like the inbox filters, so a particular
 * window can be sent to somebody. The ceiling is the API's: every one of
 * these is a full scan of a table that only grows, and a request for five
 * years is a request that takes the database with it.
 */
export function windowOf(value: string | undefined): number {
  const days = Number(value ?? DEFAULT_DAYS);

  return WINDOWS.includes(days) ? days : DEFAULT_DAYS;
}

export function DaysPicker({ path, days }: { path: string; days: number }) {
  return (
    <nav
      className="flex flex-wrap items-center gap-4 border-y py-3 text-sm"
      aria-label="Window"
    >
      {WINDOWS.map((window) => (
        <ConsoleLink
          key={window}
          href={`${path}?days=${window}`}
          className={
            days === window
              ? "font-medium underline underline-offset-4"
              : "text-muted-foreground underline-offset-4 hover:underline"
          }
        >
          {window === 365 ? "A year" : `${window} days`}
        </ConsoleLink>
      ))}
    </nav>
  );
}
