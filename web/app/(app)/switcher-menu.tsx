"use client";

import { Check, ChevronsUpDown, Plus } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { switchWorkspace } from "@/lib/workspace-actions";
import type { Workspace } from "@/lib/types";

/**
 * The menu itself.
 *
 * Each row is a form posting to a server action rather than a link,
 * because switching sets a cookie and a GET that changes something is a GET
 * a prefetcher will eventually make on somebody's behalf.
 *
 * A suspended workspace is listed and labelled rather than hidden. It can
 * still be read -- that is the whole shape of a suspension in this API --
 * and a business that cannot find its own inbox during one would be worse
 * off than the suspension intends.
 */
export function SwitcherMenu({
  active,
  workspaces,
}: {
  active: Workspace;
  workspaces: Workspace[];
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="gap-1.5 font-normal"
          data-testid="workspace-switcher"
        >
          {active.name}
          {active.status !== "active" ? (
            <Badge variant="secondary" className="text-[10px] uppercase">
              {active.status}
            </Badge>
          ) : null}
          <ChevronsUpDown className="text-muted-foreground size-3.5" />
        </Button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="start" className="w-60">
        <DropdownMenuLabel className="text-muted-foreground text-xs font-normal">
          Your workspaces
        </DropdownMenuLabel>

        {workspaces.map((workspace) => (
          <form action={switchWorkspace} key={workspace.id}>
            <input type="hidden" name="workspace_id" value={workspace.id} />
            <DropdownMenuItem asChild>
              <button type="submit" className="w-full">
                <Check
                  className={
                    workspace.id === active.id
                      ? "size-4 opacity-100"
                      : "size-4 opacity-0"
                  }
                />
                <span className="truncate">{workspace.name}</span>
                {workspace.status !== "active" ? (
                  <span className="text-muted-foreground ml-auto text-[10px] uppercase">
                    {workspace.status}
                  </span>
                ) : null}
              </button>
            </DropdownMenuItem>
          </form>
        ))}

        <DropdownMenuSeparator />

        <DropdownMenuItem asChild>
          <Link href="/workspaces">
            <Plus className="size-4" />
            New workspace
          </Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
