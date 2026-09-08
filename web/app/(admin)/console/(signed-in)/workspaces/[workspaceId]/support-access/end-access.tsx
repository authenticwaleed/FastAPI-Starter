import { Button } from "@/components/ui/button";
import { endSupportAccess } from "@/lib/console-actions";

/**
 * Close your own window before it runs out.
 *
 * A plain form and no confirmation, which is the right shape for the
 * safest request on this surface: it takes access away rather than
 * granting it, and the worst outcome of pressing it by accident is asking
 * again. The API answers the same way whether or not there was anything
 * to end, so there is no failure state to render either.
 *
 * Yours and only yours. Taking a colleague's access away is a different
 * act with a different rank behind it, and the API does not offer it here.
 */
export function EndAccess({ workspaceId }: { workspaceId: string }) {
  return (
    <form action={endSupportAccess}>
      <input type="hidden" name="workspace_id" value={workspaceId} />
      <Button type="submit" variant="outline" size="sm">
        End my access now
      </Button>
    </form>
  );
}
