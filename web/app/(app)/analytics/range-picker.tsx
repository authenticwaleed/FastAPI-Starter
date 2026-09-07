import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/**
 * The range, in the address.
 *
 * A form that navigates rather than client state, so a particular window
 * can be bookmarked, opened in a second tab and sent to a colleague — the
 * same reason the inbox filters are links. "Last month's numbers" should
 * be a thing you can paste into a message.
 *
 * Empty is not a missing value: the API's own default window applies, and
 * saying "the last 30 days" beside the empty fields is more honest than
 * pre-filling two dates and implying somebody chose them.
 */
export function RangePicker({
  start,
  end,
}: {
  start: string | null;
  end: string | null;
}) {
  return (
    <form
      action="/analytics"
      className="flex flex-wrap items-end gap-3 border-y py-3"
    >
      <div className="grid gap-1.5">
        <Label htmlFor="start" className="text-xs">
          From
        </Label>
        <Input
          id="start"
          name="start"
          type="date"
          defaultValue={start ?? ""}
          className="h-8 w-40"
        />
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="end" className="text-xs">
          To
        </Label>
        <Input
          id="end"
          name="end"
          type="date"
          defaultValue={end ?? ""}
          className="h-8 w-40"
        />
      </div>

      <Button type="submit" variant="outline" size="sm">
        Apply
      </Button>

      {start || end ? (
        <Link
          href="/analytics"
          className="text-muted-foreground text-sm underline-offset-4 hover:underline"
        >
          Clear
        </Link>
      ) : (
        <span className="text-muted-foreground text-xs">
          Showing the API&rsquo;s default window.
        </span>
      )}
    </form>
  );
}
