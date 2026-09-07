"use client";

import {
  BarChart3,
  Building2,
  CreditCard,
  KeyRound,
  LogOut,
  Plug,
  ScrollText,
  User as UserIcon,
  Zap,
} from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { signOut } from "@/lib/auth-actions";
import type { User } from "@/lib/types";

/**
 * Who is signed in, and the two places that are about them rather than
 * about a workspace.
 *
 * Signing out is a form and not a link, because it spends the refresh token
 * at the API -- a GET that changes something is one a prefetcher will
 * eventually make on somebody's behalf.
 */
export function AccountMenu({ user }: { user: User }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="font-normal"
          data-testid="account-menu"
        >
          {user.name}
        </Button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="grid gap-0.5">
          <span className="truncate text-sm">{user.name}</span>
          <span className="text-muted-foreground truncate text-xs font-normal">
            {user.email}
          </span>
        </DropdownMenuLabel>

        <DropdownMenuSeparator />

        <DropdownMenuItem asChild>
          <Link href="/account">
            <UserIcon className="size-4" />
            Account
          </Link>
        </DropdownMenuItem>

        <DropdownMenuItem asChild>
          <Link href="/workspaces">
            <Building2 className="size-4" />
            Workspaces
          </Link>
        </DropdownMenuItem>

        <DropdownMenuItem asChild>
          <Link href="/analytics">
            <BarChart3 className="size-4" />
            Analytics
          </Link>
        </DropdownMenuItem>

        <DropdownMenuItem asChild>
          <Link href="/automations">
            <Zap className="size-4" />
            Automations
          </Link>
        </DropdownMenuItem>

        <DropdownMenuItem asChild>
          <Link href="/integrations">
            <Plug className="size-4" />
            Integrations
          </Link>
        </DropdownMenuItem>

        <DropdownMenuItem asChild>
          <Link href="/audit">
            <ScrollText className="size-4" />
            Audit log
          </Link>
        </DropdownMenuItem>

        <DropdownMenuItem asChild>
          <Link href="/api-keys">
            <KeyRound className="size-4" />
            API keys
          </Link>
        </DropdownMenuItem>

        <DropdownMenuItem asChild>
          <Link href="/billing">
            <CreditCard className="size-4" />
            Plan and billing
          </Link>
        </DropdownMenuItem>

        <DropdownMenuSeparator />

        <form action={signOut}>
          <DropdownMenuItem asChild>
            <button type="submit" className="w-full">
              <LogOut className="size-4" />
              Sign out
            </button>
          </DropdownMenuItem>
        </form>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
