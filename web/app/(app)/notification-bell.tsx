import { Bell } from "lucide-react";
import Link from "next/link";

import { api } from "@/lib/api";
import type { UnreadCount } from "@/lib/types";

/**
 * What the badge shows.
 *
 * Its own endpoint rather than a count taken off the feed, because the API
 * separated them for exactly this reason: a badge is asked far more often
 * than a feed is opened, and a count is one query where a page is two.
 *
 * Not polled. Every mutation that could change this revalidates the layout,
 * so the number is refreshed by the thing that moved it rather than by a
 * timer running on every open tab.
 */
export async function NotificationBell() {
  const { unread } = await api<UnreadCount>("/notifications/unread-count");

  return (
    <Link
      href="/notifications"
      className="hover:bg-accent relative grid size-8 place-items-center rounded-md"
      aria-label={
        unread === 0 ? "Notifications" : `Notifications, ${unread} unread`
      }
      data-testid="notification-bell"
    >
      <Bell className="size-4" />
      {unread > 0 ? (
        <span
          className="bg-primary text-primary-foreground absolute -top-0.5 -right-0.5 grid min-w-4 place-items-center rounded-full px-1 text-[10px] leading-4 tabular-nums"
          data-testid="unread-count"
        >
          {/*
            Capped for width, not for truth. The aria-label above carries
            the real number, so a screen reader is never told "99+".
          */}
          {unread > 99 ? "99+" : unread}
        </span>
      ) : null}
    </Link>
  );
}
