import Link from "next/link";

import { SwitcherMenu } from "./switcher-menu";
import { activeWorkspace, listWorkspaces } from "@/lib/workspace";

/**
 * Which business is being looked at.
 *
 * A server component, so the first render already knows -- the active
 * workspace is a cookie rather than client state precisely so this does not
 * have to arrive after a round trip and shift the header under the cursor.
 *
 * Somebody with no workspace gets a link rather than an empty dropdown. A
 * control that opens onto nothing is worse than one that says what to do.
 */
export async function WorkspaceSwitcher() {
  const [workspaces, active] = await Promise.all([listWorkspaces(), activeWorkspace()]);

  if (!active) {
    return (
      <Link
        href="/workspaces"
        className="text-muted-foreground hover:text-foreground border-l pl-4 text-sm underline-offset-4 hover:underline"
        data-testid="workspace-switcher"
      >
        Create a workspace
      </Link>
    );
  }

  return <SwitcherMenu active={active} workspaces={workspaces} />;
}
