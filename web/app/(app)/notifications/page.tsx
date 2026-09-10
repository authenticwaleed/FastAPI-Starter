import type { Metadata } from "next";

import { NotificationList } from "./notification-list";
import { FilterTabs } from "@/components/filter-tabs";
import { PageHeader } from "@/components/page-header";
import { Pagination } from "@/components/pagination";
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

  return (
    <div className="grid gap-6">
      <PageHeader
        title="Notifications"
        description="Everything you have been told, across every workspace."
      />

      <FilterTabs
        label="Show"
        options={[
          {
            value: "all",
            label: "All",
            href: "/notifications",
            active: !unreadOnly,
          },
          {
            value: "unread",
            label: "Unread",
            href: "/notifications?unread=1",
            active: unreadOnly,
          },
        ]}
      />

      <NotificationList items={feed.items} workspaceNames={Object.fromEntries(names)} />

      <Pagination
        page={feed.page}
        total={feed.total}
        pageSize={feed.page_size}
        noun="notifications"
        labels={{ previous: "Newer", next: "Older" }}
        href={(to) =>
          `/notifications?page=${to}${unreadOnly ? "&unread=1" : ""}`
        }
      />
    </div>
  );
}
