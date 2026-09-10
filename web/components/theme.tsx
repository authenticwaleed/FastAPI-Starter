"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useSyncExternalStore } from "react";

import { cn } from "@/lib/utils";

/**
 * Light, dark, or whatever the machine says.
 *
 * The whole mechanism is two pieces and neither of them is a provider.
 *
 * `ThemeScript` runs once, synchronously, before the first paint, and puts
 * the `dark` class on `<html>` if it belongs there. It reads the cookie
 * itself rather than being told by the server, and that is the point: the
 * root layout stays static, so `/register` and `/pricing` are still
 * prerendered. A layout that called `cookies()` to answer a question about
 * colour would make every route in the client dynamic to do it.
 *
 * `ThemeToggle` writes that cookie and flips the same class. No context, no
 * re-render of anything above it, and no state to keep in sync -- the class
 * on `<html>` *is* the state, and CSS reads it directly.
 */

const COOKIE = "baton_theme";
const YEAR = 60 * 60 * 24 * 365;

type Theme = "light" | "dark" | "system";

const OPTIONS: { value: Theme; label: string; Icon: typeof Sun }[] = [
  { value: "light", label: "Light", Icon: Sun },
  { value: "dark", label: "Dark", Icon: Moon },
  { value: "system", label: "Match system", Icon: Monitor },
];

/*
 * Inlined, blocking, and first in the body.
 *
 * Anything deferred -- an effect, a `next/script` strategy that waits for
 * hydration -- paints the light theme first and then corrects itself,
 * which is the white flash people turn dark mode off over.
 *
 * It re-reads the cookie on every call rather than closing over it, so the
 * listener below stays right for somebody who picks "match system" later
 * in the session. That listener covers a machine switching at sunset with
 * the tab open.
 *
 * Every line is in a `try`. A browser with cookies disabled is a browser
 * that gets the light theme, not one that gets a blank page.
 */
const SCRIPT = `(function(){try{
var re=/(?:^|;\\s*)${COOKIE}=(light|dark|system)/;
var q=window.matchMedia("(prefers-color-scheme: dark)");
var f=function(){var m=document.cookie.match(re),t=m?m[1]:"system";
document.documentElement.classList.toggle("dark",t==="dark"||(t==="system"&&q.matches))};
f();if(q.addEventListener)q.addEventListener("change",f);
}catch(e){}})()`;

export function ThemeScript() {
  return <script dangerouslySetInnerHTML={{ __html: SCRIPT }} />;
}

/*
 * The cookie, subscribed to as what it is: state living outside React.
 *
 * `useSyncExternalStore` rather than `useState` filled in by an effect,
 * which is the same thing written as a bug -- it renders once with a guess
 * and then corrects itself, and React reports that correction as a
 * cascading render.
 *
 * The server snapshot is `null` because the server genuinely does not
 * know: it never read the cookie, deliberately, so that the root layout
 * stays static. React uses that value while hydrating, so the markup
 * matches, and re-reads immediately after.
 */
const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);

  return () => {
    listeners.delete(listener);
  };
}

function read(): Theme {
  const match = document.cookie.match(
    new RegExp(`(?:^|;\\s*)${COOKIE}=(light|dark|system)`),
  );

  return (match?.[1] as Theme) ?? "system";
}

function unknown(): null {
  return null;
}

function choose(theme: Theme) {
  document.cookie = `${COOKIE}=${theme};path=/;max-age=${YEAR};samesite=lax`;

  const dark =
    theme === "dark" ||
    (theme === "system" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);

  document.documentElement.classList.toggle("dark", dark);

  for (const listener of listeners) listener();
}

export function ThemeToggle({ className }: { className?: string }) {
  const theme = useSyncExternalStore(subscribe, read, unknown);

  return (
    <div
      role="group"
      aria-label="Colour theme"
      className={cn(
        "border-border bg-surface-muted inline-flex items-center gap-0.5 rounded-md border p-0.5",
        className,
      )}
    >
      {OPTIONS.map(({ value, label, Icon }) => (
        <button
          key={value}
          type="button"
          title={label}
          aria-label={label}
          aria-pressed={theme === null ? undefined : theme === value}
          className={cn(
            "text-muted-foreground hover:text-foreground grid size-6 place-items-center rounded-sm transition-colors",
            "aria-pressed:bg-surface aria-pressed:text-foreground aria-pressed:shadow-raised",
          )}
          onClick={() => choose(value)}
        >
          <Icon className="size-3.5" aria-hidden="true" />
        </button>
      ))}
    </div>
  );
}
