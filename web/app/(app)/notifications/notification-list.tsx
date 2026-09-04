"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { FormError } from "@/components/form";
import { Button } from "@/components/ui/button";
import { markAllRead, markRead } from "@/lib/notification-actions";
import type { FormState } from "@/lib/form-state";
import type { Notification } from "@/lib/types";

function when(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function MarkAllButton() {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" variant="outline" size="sm" disabled={pending}>
      Mark all as read
    </Button>
  );
}

/**
 * The feed.
 *
 * Marking one read is a form per row rather than a click handler, so it
 * works before the page has hydrated and needs no fetch of its own. Each
 * action revalidates the layout, which is what makes the badge in the
 * header clear without the feed being fetched again from scratch.
 */
export function NotificationList({
  items,
  workspaceNames,
}: {
  items: Notification[];
  workspaceNames: Record<string, string>;
}) {
  const [readState, readOne] = useActionState<FormState, FormData>(markRead, null);
  const [allState, readAll] = useActionState<FormState, FormData>(markAllRead, null);

  if (items.length === 0) {
    return (
      <p className="text-muted-foreground rounded-md border border-dashed px-4 py-8 text-center text-sm">
        Nothing here. Notifications arrive when something needs you — a
        payment that did not go through, a conversation handed to you.
      </p>
    );
  }

  return (
    <div className="grid gap-4">
      <div className="flex items-center gap-3">
        <form action={readAll}>
          <MarkAllButton />
        </form>
        {allState?.done ? (
          <span className="text-muted-foreground text-sm" role="status">
            {allState.marked === 0
              ? "Nothing was unread."
              : `Cleared ${allState.marked}.`}
          </span>
        ) : null}
      </div>

      <FormError>{readState?.error ?? allState?.error}</FormError>

      <ul className="grid gap-2">
        {items.map((item) => (
          <li
            key={item.id}
            data-unread={item.read_at === null ? "" : undefined}
            className="flex flex-wrap items-start gap-x-3 gap-y-2 rounded-md border px-3 py-2.5 data-unread:border-l-2 data-unread:border-l-primary"
          >
            <div className="grid min-w-0 flex-1 gap-0.5">
              <span className="text-sm font-medium">{item.title}</span>
              {item.body ? (
                <span className="text-muted-foreground text-sm">{item.body}</span>
              ) : null}
              <span className="text-muted-foreground text-xs">
                {workspaceNames[item.workspace_id] ?? "A workspace you have left"} ·{" "}
                {when(item.created_at)}
              </span>
            </div>

            {item.read_at === null ? (
              <form action={readOne}>
                <input type="hidden" name="notification_id" value={item.id} />
                <Button type="submit" variant="ghost" size="sm">
                  Mark read
                </Button>
              </form>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
