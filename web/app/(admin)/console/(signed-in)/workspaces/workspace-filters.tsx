import { ConsoleLink } from "@/components/console/console-link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";

/**
 * The three narrowings a support ticket needs, in the address bar.
 *
 * A plain GET form and two native selects rather than the app's Radix
 * picker: this submits by navigating, so it works before any JavaScript
 * has run and leaves a URL a colleague can be sent. "Every suspended
 * workspace on the growth plan" should be a link in a message.
 *
 * `status` and `plan` narrow; only `q` searches. Both send nothing when
 * empty, because an empty string is not a status the API knows and it
 * would rather say so than guess.
 */
const STATUSES = ["active", "suspended", "cancelled"];
const PLANS = ["starter", "growth", "business"];

export function WorkspaceFilters({
  q,
  status,
  plan,
}: {
  q: string | null;
  status: string | null;
  plan: string | null;
}) {
  return (
    <form
      action="/console/workspaces"
      className="flex flex-wrap items-end gap-3 border-y py-3"
    >
      <div className="grid gap-1.5">
        <Label htmlFor="q" className="text-xs">
          Name, address, or anyone in it
        </Label>
        <Input
          id="q"
          name="q"
          type="search"
          defaultValue={q ?? ""}
          maxLength={320}
          className="w-72"
        />
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="status" className="text-xs">
          Status
        </Label>
        <NativeSelect id="status" name="status" defaultValue={status ?? ""}>
          <option value="">Any</option>
          {STATUSES.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </NativeSelect>
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="plan" className="text-xs">
          Plan
        </Label>
        <NativeSelect id="plan" name="plan" defaultValue={plan ?? ""}>
          <option value="">Any</option>
          {PLANS.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </NativeSelect>
      </div>

      <Button type="submit" variant="outline" size="sm">
        Search
      </Button>

      {q || status || plan ? (
        <ConsoleLink
          href="/console/workspaces"
          className="text-muted-foreground text-sm underline-offset-4 hover:underline"
        >
          Clear
        </ConsoleLink>
      ) : null}
    </form>
  );
}
