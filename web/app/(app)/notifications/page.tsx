import type { Metadata } from "next";
import Link from "next/link";

import { NotificationList } from "./notification-list";
import { api } from "@/lib/api";
import type { Notification, Page, Workspace } from "@/lib/types";
import { listWorkspaces } from "@/lib/workspace";

export const metadata: Metadata = { title: "Notifications" };

const PAGE_SIZE = 20;

/**
 * One feed, across every business.
 *
 * No workspace in the path, which is the API's design and not an oversight:
 * a notification is addressed to a person, and a person has one feed however
 * many businesses they work in. Each row says which workspace it came from,
 * so the names are resolved once here rather than per row.
 */
export default async function NotificationsPage({
  searchParams,
}: {
  searchParams: Promise<{ page?: string; unread?: string }>;
}) {
  const { page: rawPage, unread } = await searchParams;

  const page = Math.max(1, Number(rawPage ?? 1) || 1);
  const unreadOnly = unread === "1";

  const query = new URLSearchParams({
    page: String(page),
    page_size: String(PAGE_SIZE),
    unread_only: String(unreadOnly),
  });

  const [feed, workspaces] = await Promise.all([
    api<Page<Notification>>(`/notifications?${query}`),
    listWorkspaces(),
  ]);

  const names = new Map(workspaces.map((w: Workspace) => [w.id, w.name]));
  const lastPage = Math.max(1, Math.ceil(feed.total / feed.page_size));

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Notifications</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Everything you have been told, across every workspace.
          </p>
        </div>

        <div className="flex gap-3 text-sm">
          <Link
            href="/notifications"
            className={
              unreadOnly
                ? "text-muted-foreground underline-offset-4 hover:underline"
                : "font-medium underline underline-offset-4"
            }
          >
            All
          </Link>
          <Link
            href="/notifications?unread=1"
            className={
              unreadOnly
                ? "font-medium underline underline-offset-4"
                : "text-muted-foreground underline-offset-4 hover:underline"
            }
          >
            Unread
          </Link>
        </div>
      </div>

      <NotificationList items={feed.items} workspaceNames={Object.fromEntries(names)} />

      {lastPage > 1 ? (
        <nav className="flex items-center justify-between text-sm" aria-label="Pages">
          <span className="text-muted-foreground tabular-nums">
            Page {feed.page} of {lastPage} · {feed.total} in total
          </span>
          <span className="flex gap-3">
            {page > 1 ? (
              <Link
                href={`/notifications?page=${page - 1}${unreadOnly ? "&unread=1" : ""}`}
                className="underline underline-offset-4"
              >
                Newer
              </Link>
            ) : null}
            {page < lastPage ? (
              <Link
                href={`/notifications?page=${page + 1}${unreadOnly ? "&unread=1" : ""}`}
                className="underline underline-offset-4"
              >
                Older
              </Link>
            ) : null}
          </span>
        </nav>
      ) : null}
    </div>
  );
}
