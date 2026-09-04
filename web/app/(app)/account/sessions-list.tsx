"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { FormError } from "@/components/form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { revokeAllSessions, revokeSession } from "@/lib/account-actions";
import type { FormState } from "@/lib/form-state";
import type { Session } from "@/lib/types";

/**
 * A device, described by what it told us.
 *
 * Both the agent string and the address are best effort and are here to be
 * recognised rather than trusted -- a browser sends whatever User-Agent it
 * likes, and an address can belong to a phone network's proxy. The screen
 * says as much rather than presenting them as evidence.
 */
function describe(session: Session): string {
  if (!session.user_agent) return "An unnamed device";

  const agent = session.user_agent;
  const browser =
    /Firefox\//.test(agent) ? "Firefox"
    : /Edg\//.test(agent) ? "Edge"
    : /Chrome\//.test(agent) ? "Chrome"
    : /Safari\//.test(agent) ? "Safari"
    : "A browser";

  const platform =
    /Android/.test(agent) ? "Android"
    : /iPhone|iPad/.test(agent) ? "iOS"
    : /Mac OS X/.test(agent) ? "macOS"
    : /Windows/.test(agent) ? "Windows"
    : /Linux/.test(agent) ? "Linux"
    : null;

  return platform ? `${browser} on ${platform}` : browser;
}

function when(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function RevokeButton({ current }: { current: boolean }) {
  const { pending } = useFormStatus();

  return (
    <Button
      type="submit"
      variant={current ? "destructive" : "outline"}
      size="sm"
      disabled={pending}
    >
      {current ? "Sign out here" : "Sign out"}
    </Button>
  );
}

export function SessionsList({ sessions }: { sessions: Session[] }) {
  const [state, action] = useActionState<FormState, FormData>(revokeSession, null);

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Where you are signed in</h2>
        </CardTitle>
        <CardDescription>
          Live sessions only. The device and address are what each browser
          reported, so treat them as recognisable rather than as proof.
        </CardDescription>
      </CardHeader>

      <CardContent className="grid gap-4">
        <FormError>{state?.error}</FormError>

        <ul className="grid gap-2">
          {sessions.map((session) => (
            <li
              key={session.id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-2"
            >
              <div className="grid min-w-0 flex-1 gap-0.5">
                <span className="flex items-center gap-2 text-sm">
                  {describe(session)}
                  {session.current ? (
                    <Badge variant="secondary">This device</Badge>
                  ) : null}
                </span>
                <span className="text-muted-foreground truncate text-xs">
                  {session.ip_address ?? "address unknown"} · last used{" "}
                  {when(session.last_used_at)}
                </span>
              </div>

              <form action={action}>
                <input type="hidden" name="session_id" value={session.id} />
                <input
                  type="hidden"
                  name="current"
                  value={session.current ? "1" : "0"}
                />
                {/*
                  Ending the current session is allowed and is a sign-out,
                  not an error. The button says which one this is so nobody
                  does it by accident.
                */}
                <RevokeButton current={session.current} />
              </form>
            </li>
          ))}
        </ul>

        <form action={revokeAllSessions}>
          <Button type="submit" variant="outline" size="sm">
            Sign out everywhere
          </Button>
          <p className="text-muted-foreground mt-2 text-xs">
            This device included. Access already granted lasts a few more
            minutes; nothing can be renewed after that.
          </p>
        </form>
      </CardContent>
    </Card>
  );
}
