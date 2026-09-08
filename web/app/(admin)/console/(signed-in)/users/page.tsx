import type { Metadata } from "next";

import { ConsoleLink } from "@/components/console/console-link";
import { ConsoleHeading } from "@/components/console/heading";
import { ConsolePages } from "@/components/console/pages";
import { consoleRefusal } from "@/components/console/refusal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { searchUsers } from "@/lib/console";
import { day } from "@/lib/console-labels";
import type { AdminUserSummary, Page as Paged } from "@/lib/types";

export const metadata: Metadata = { title: "Accounts" };

/**
 * The other direction a ticket arrives from.
 *
 * Sometimes it names a business; sometimes it is somebody who cannot sign
 * in and does not know which businesses they are in. The API matches a
 * fragment anywhere in an address or a name, because that is what a
 * signature or half a company address gives you — an id almost never is.
 */
export default async function ConsoleUsersPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; page?: string }>;
}) {
  const { q, page: rawPage } = await searchParams;
  const page = Math.max(1, Number(rawPage ?? 1) || 1);

  let found: Paged<AdminUserSummary>;

  try {
    found = await searchUsers({ q, page });
  } catch (error) {
    return consoleRefusal(error, {
      title: "Accounts",
      missing: "No such account.",
    });
  }

  return (
    <div className="grid gap-6">
      <ConsoleHeading
        title="Accounts"
        description="Everybody who has registered, whether or not they are in a workspace."
      />

      <form
        action="/console/users"
        className="flex flex-wrap items-end gap-3 border-y py-3"
      >
        <div className="grid gap-1.5">
          <Label htmlFor="q" className="text-xs">
            Address or name
          </Label>
          <Input
            id="q"
            name="q"
            type="search"
            defaultValue={q ?? ""}
            maxLength={320}
            className="h-8 w-72"
          />
        </div>

        <Button type="submit" variant="outline" size="sm">
          Search
        </Button>

        {q ? (
          <ConsoleLink
            href="/console/users"
            className="text-muted-foreground text-sm underline-offset-4 hover:underline"
          >
            Clear
          </ConsoleLink>
        ) : null}
      </form>

      {found.items.length === 0 ? (
        <p className="text-muted-foreground rounded-md border border-dashed px-4 py-8 text-center text-sm">
          Nobody matches that.
        </p>
      ) : (
        <ul className="grid gap-2" data-testid="user-results">
          {found.items.map((user) => (
            <li key={user.id}>
              <ConsoleLink
                href={`/console/users/${user.id}`}
                className="hover:bg-accent/50 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-2.5"
              >
                <span className="text-sm font-medium">{user.name}</span>
                <span className="text-muted-foreground truncate text-xs">
                  {user.email}
                </span>

                <span className="text-muted-foreground ml-auto text-xs">
                  Registered {day(user.created_at)}
                </span>

                {/*
                  Two states worth seeing in a list, because they are the
                  two answers to "they say they cannot get in".
                */}
                {user.is_active ? null : (
                  <Badge variant="destructive">deactivated</Badge>
                )}
                {user.email_verified_at === null ? (
                  <Badge variant="outline">unverified</Badge>
                ) : null}
              </ConsoleLink>
            </li>
          ))}
        </ul>
      )}

      <ConsolePages
        page={page}
        total={found.total}
        pageSize={found.page_size}
        noun="accounts"
        href={(to) => `/console/users?${q ? `q=${encodeURIComponent(q)}&` : ""}page=${to}`}
      />
    </div>
  );
}
