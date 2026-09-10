"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Copy, and say that it copied.
 *
 * Written twice already, identically, for the two values in this client
 * that are shown once and never again: an invitation link and a new API
 * key. Both are values somebody has to get out of the browser and into
 * somewhere else within the next few seconds, and both had the same
 * careful decision in them, which is worth keeping in one place --
 *
 * A clipboard that refuses is not an error. Permission can be denied, the
 * page can be insecure, the API can simply be absent; in every one of
 * those the value is still on screen and still selectable, which is what
 * `select-all` is for. Turning that into a red message would be telling
 * somebody a thing has gone wrong when nothing has.
 */
export function CopyButton({
  value,
  label = "Copy",
  className,
}: {
  value: string;
  label?: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className={className}
      onClick={() => {
        void navigator.clipboard?.writeText(value).then(
          () => setCopied(true),
          () => setCopied(false),
        );
      }}
    >
      {copied ? (
        <Check className="text-success" aria-hidden="true" />
      ) : (
        <Copy aria-hidden="true" />
      )}
      {/*
        The word changes and the icon changes with it. Confirming a copy
        with a tick alone leaves the one person who most needs the
        confirmation -- somebody who cannot see it -- with a button whose
        label never moved.
      */}
      {copied ? "Copied" : label}
    </Button>
  );
}

/**
 * A value on screen, next to the button that takes it away.
 *
 * `select-all` so one click selects the whole thing, and `truncate` rather
 * than wrapping: a key broken across two lines is a key somebody
 * hand-copies and gets wrong.
 */
export function CopyField({
  value,
  mono = false,
  className,
  ...props
}: React.ComponentProps<"code"> & { value: string; mono?: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <code
        className={cn(
          "bg-muted text-foreground min-w-0 flex-1 truncate rounded-md px-2 py-1.5 text-xs select-all",
          mono && "font-mono",
          className,
        )}
        {...props}
      >
        {value}
      </code>

      <CopyButton value={value} />
    </div>
  );
}
