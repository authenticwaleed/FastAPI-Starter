import { ConsoleLink } from "@/components/console/console-link";

/**
 * The top of a console screen.
 *
 * Shared because ten screens want the same three lines, and because the
 * back link is load-bearing here in a way it is not in the customer app: a
 * workspace's members, subscription, usage and integrations are four
 * separate screens precisely so that opening one does not read the other
 * three, and the way back to the workspace has to be a link somebody
 * follows rather than a fan-out somebody pays for.
 */
export function ConsoleHeading({
  title,
  description,
  back,
}: {
  title: string;
  description?: React.ReactNode;
  back?: { href: string; label: string };
}) {
  return (
    <div className="grid gap-1">
      {back ? (
        <ConsoleLink
          href={back.href}
          className="text-muted-foreground w-fit text-xs underline-offset-4 hover:underline"
        >
          ← {back.label}
        </ConsoleLink>
      ) : null}

      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>

      {description ? (
        <p className="text-muted-foreground text-sm">{description}</p>
      ) : null}
    </div>
  );
}
