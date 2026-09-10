import { Badge } from "@/components/ui/badge";

/**
 * What a state *means*, rather than what colour somebody reached for.
 *
 * Seventy-nine badges in this client, and most of them chose their variant
 * in a ternary written on the spot. Which is how `cancelled` came out grey
 * on one screen and outlined on the next, and how `past_due` -- a bill to
 * chase -- ended up in the same red as `suspended`, which is an account
 * somebody switched off.
 *
 * So the choice is made once, from six meanings:
 *
 * - `neutral`  — the ordinary state. Active, open, live. Says nothing.
 * - `quiet`    — over, and uninteresting. Archived, ended, closed.
 * - `pending`  — not finished, nobody is at fault. Queued, draft, invited.
 * - `positive` — finished and it worked. Delivered, confirmed, verified.
 * - `caution`  — needs somebody. Past due, expiring, approaching a limit.
 * - `critical` — wrong. Failed, suspended, blocked, revoked.
 *
 * None of them is colour alone: the badge always carries its own word, and
 * `data-status` carries the API's, so a test and a screen reader both read
 * the state rather than the shade.
 */
export type Tone =
  | "neutral"
  | "quiet"
  | "pending"
  | "positive"
  | "caution"
  | "critical";

const VARIANT = {
  neutral: "secondary",
  quiet: "muted",
  pending: "outline",
  positive: "success",
  caution: "warning",
  critical: "destructive",
} as const;

export function StatusBadge({
  tone,
  status,
  children,
  className,
}: {
  tone: Tone;
  /** The API's own word for it, for tests and for anyone reading the DOM. */
  status?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Badge
      variant={VARIANT[tone]}
      data-status={status}
      data-tone={tone}
      className={className}
    >
      {children}
    </Badge>
  );
}
