import { ConsoleHeading } from "@/components/console/heading";
import { ErrorState } from "@/components/error-state";
import { ApiError } from "@/lib/errors";

/**
 * A refusal, as the console shows one.
 *
 * Deliberately plain: a heading, a sentence, and nothing to click. That is
 * the phase's rule about `address_not_allowed` read literally, and it is
 * right for the rest too — none of the refusals this surface hands out is
 * fixed by trying again, and a button under one teaches somebody to press
 * it before reading it.
 *
 * The shared `ErrorState`, which prints the code under the sentence. On
 * this surface that is worth having: whoever is reading is staff, and the
 * stable code is the half of this worth quoting into a ticket.
 */
export function ConsoleRefused({
  title,
  sentence,
  code,
}: {
  title: string;
  sentence: string;
  code?: string;
}) {
  return (
    <div className="grid gap-6">
      <ConsoleHeading title={title} />

      <ErrorState
        title={sentence}
        code={code}
        data-testid="console-refusal"
      />
    </div>
  );
}

/**
 * The four refusals every console screen can meet, answered in one place.
 *
 * A screen that worded `insufficient_staff_role` for itself would disagree
 * with the next one, which is principle 4 applied to a surface where every
 * screen shares the same door. Anything else is re-thrown: an unexpected
 * failure should look like one.
 *
 * The 404 is the one the caller words, and it is the interesting one. On
 * the tenant surface a 404 is deliberately ambiguous — "no such workspace"
 * covers both a workspace that does not exist and one you are not in, so
 * that an id cannot be used to discover which businesses have accounts
 * (§3.2). Here the opposite holds: whoever is reading is authenticated
 * staff and is already being recorded, so the console says plainly that
 * there is no such row. The same code from the API, a different surface,
 * a different sentence — which is why this one comes from the screen
 * rather than from the code map.
 */
export function consoleRefusal(
  error: unknown,
  { title, missing }: { title: string; missing: string },
): React.ReactNode {
  if (!(error instanceof ApiError)) throw error;

  if (error.status !== 403 && error.status !== 404 && error.status !== 429) {
    throw error;
  }

  return (
    <ConsoleRefused
      title={title}
      sentence={error.status === 404 ? missing : error.sentence}
      code={error.code}
    />
  );
}
