import Link from "next/link";

/**
 * Every link in the console, with prefetching off.
 *
 * A wrapper rather than a prop somebody remembers, because the rule it
 * keeps is the one this whole phase is judged on. Next prefetches a link
 * that enters the viewport, and a prefetched console route is a server
 * render, which is a read of `/admin`, which writes a row to the platform
 * audit log naming a workspace nobody opened. Do that on a page of fifty
 * search results and the log stops being able to answer the only question
 * it exists for.
 *
 * `prefetch={false}` after the spread, so a caller cannot turn it back on
 * without editing this file and reading the paragraph above.
 */
export function ConsoleLink(props: React.ComponentProps<typeof Link>) {
  return <Link {...props} prefetch={false} />;
}
