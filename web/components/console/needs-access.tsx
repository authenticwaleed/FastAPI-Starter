import { RequestAccess } from "@/components/console/request-access";
import { ConsoleHeading } from "@/components/console/heading";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { sentenceFor } from "@/lib/errors";

/**
 * The refusal this whole phase is built around, answered where it happened.
 *
 * `support_access_required` must read as **ask for access** rather than as
 * a fault, and the acceptance is that the screen offers the request flow
 * rather than pointing at one. So the form is here, on the page somebody
 * was refused, and asking from it brings them back to what they wanted.
 *
 * It covers a grant that never existed, one that expired and one that was
 * revoked, because all three mean the same thing to the person asking and
 * lead to the same next step. That is the one place this surface answers
 * three states with one sentence, and it is deliberate.
 *
 * Not rendered by `consoleRefusal`, which is for the refusals with nothing
 * to be done about them. This one has exactly one thing to do about it.
 */
export function NeedsAccess({
  title,
  workspaceId,
}: {
  title: string;
  workspaceId: string;
}) {
  return (
    <div className="grid gap-6">
      <ConsoleHeading
        title={title}
        back={{ href: `/console/workspaces/${workspaceId}`, label: "Workspace" }}
      />

      <Alert role="alert" data-testid="needs-access" data-code="support_access_required">
        <AlertDescription>{sentenceFor("support_access_required")}</AlertDescription>
      </Alert>

      <RequestAccess workspaceId={workspaceId} />
    </div>
  );
}
