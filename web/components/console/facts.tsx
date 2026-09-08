/**
 * A detail screen's rows: a label, and what the API said.
 *
 * `null` renders as an em dash and never as a blank cell or a zero. On
 * this surface that matters more than anywhere else in the client: the
 * person reading is about to say the number out loud to a customer, and
 * "we have no record of that" and "nothing has been synced" are two
 * different answers to a ticket.
 */
export function Facts({ children }: { children: React.ReactNode }) {
  return (
    <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-[10rem_1fr]">{children}</dl>
  );
}

export function Fact({
  label,
  children,
  mono = false,
}: {
  label: string;
  children?: React.ReactNode;
  /** For ids and handles, which are read character by character or copied. */
  mono?: boolean;
}) {
  const empty = children === null || children === undefined || children === "";

  return (
    <div className="grid gap-0.5 sm:col-span-2 sm:grid-cols-subgrid">
      <dt className="text-muted-foreground text-sm">{label}</dt>
      <dd
        className={`text-sm ${mono ? "font-mono text-xs break-all" : ""}`}
        data-fact={label}
      >
        {empty ? <span className="text-muted-foreground">—</span> : children}
      </dd>
    </div>
  );
}
