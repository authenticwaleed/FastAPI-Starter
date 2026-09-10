import { FieldError } from "@/components/form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

/**
 * The part of a screen that can take something away.
 *
 * Six screens grew one of these independently -- delete the account, close
 * the workspace, leave it, cancel the subscription, erase everything --
 * and each drew its own container. Two used a card with
 * `border-destructive/40`, the rest used nothing at all, so on those the
 * only thing separating "save your name" from "delete your account" was a
 * gap.
 *
 * Deliberately not a card. A card says *this belongs together*; what is
 * wanted here is *this is not like the rest of the page*, which is a
 * different job and is done by the rule down the left and by putting it at
 * the bottom, on its own.
 */
export function DangerZone({
  title,
  description,
  children,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      data-danger-zone=""
      className={cn(
        "border-destructive/30 grid gap-3 rounded-md border border-l-2 border-l-destructive px-4 py-4",
        className,
      )}
    >
      <div className="grid gap-1">
        <h2 className="text-destructive text-sm font-medium">{title}</h2>
        {description ? (
          <p className="text-muted-foreground max-w-prose text-sm">
            {description}
          </p>
        ) : null}
      </div>

      {children}
    </section>
  );
}

/**
 * Type this, exactly, before the button will do anything.
 *
 * The phrase is the subject's own name wherever there is one -- a
 * workspace's slug rather than the word DELETE -- because a phrase that is
 * the same every time is one people learn to type without reading, and the
 * whole purpose of the field is to make somebody read what they are about
 * to name.
 *
 * Where the API checks this itself (erasure does), the check here is not a
 * substitute for it and does not pretend to be: a mismatch still reaches
 * the server, and is still recorded.
 */
export function TypedConfirm({
  phrase,
  error,
  id = "confirm",
  name = "confirm",
  className,
}: {
  phrase: string;
  error?: string;
  id?: string;
  name?: string;
  className?: string;
}) {
  return (
    <div className={cn("grid max-w-sm gap-1.5", className)}>
      <Label htmlFor={id}>
        Type{" "}
        <span className="bg-muted text-foreground rounded-sm px-1 py-0.5 font-mono text-xs select-all">
          {phrase}
        </span>{" "}
        to confirm
      </Label>

      <Input
        id={id}
        name={name}
        autoComplete="off"
        autoCapitalize="none"
        autoCorrect="off"
        spellCheck={false}
        className="font-mono"
        aria-invalid={error ? true : undefined}
        required
      />

      <FieldError>{error}</FieldError>
    </div>
  );
}
