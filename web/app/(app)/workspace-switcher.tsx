/**
 * The switcher, as a stub.
 *
 * W1 has no workspaces to switch between: `/workspaces` is W2's, and the
 * active workspace is a cookie that phase sets. The space is claimed here
 * so the header does not change shape when it arrives, and so nothing
 * downstream is written against a header that has no switcher in it.
 *
 * Deliberately not a disabled dropdown. A control that opens onto nothing
 * is worse than a label saying what is coming.
 */
export function WorkspaceSwitcher() {
  return (
    <span
      className="text-muted-foreground border-l pl-4 text-sm"
      data-testid="workspace-switcher"
    >
      No workspace yet
    </span>
  );
}
