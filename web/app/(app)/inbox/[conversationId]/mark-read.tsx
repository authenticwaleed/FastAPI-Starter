"use client";

import { useEffect, useRef } from "react";

import { markConversationRead } from "@/lib/conversation-actions";

/**
 * Clear the unread count, once, after the thread has actually been read.
 *
 * In an effect rather than in the render, and that is the whole point of
 * this component existing at all. Next prefetches links on hover, so a
 * render that marked read would clear the count on every row somebody's
 * cursor crossed on the way down the inbox. A prefetch fetches the payload
 * and never mounts anything, so an effect only runs for a page a person
 * actually navigated to.
 *
 * Renders nothing, and says nothing when it fails. This is housekeeping,
 * and a toast about it would interrupt somebody mid-conversation.
 */
export function MarkRead({
  workspaceId,
  conversationId,
  unread,
}: {
  workspaceId: string;
  conversationId: string;
  unread: number;
}) {
  const done = useRef(false);

  useEffect(() => {
    if (unread === 0 || done.current) return;

    done.current = true;
    void markConversationRead(workspaceId, conversationId);
  }, [workspaceId, conversationId, unread]);

  return null;
}
