/**
 * One headline number.
 *
 * A tile rather than a one-bar chart, which is the form heuristic read
 * literally: a single current value has no shape to compare, so a bar
 * would be decoration around a number somebody could have just read.
 *
 * `null` is rendered as an em dash and never as zero. "No conversation has
 * been answered yet" and "answered instantly" are different facts, and the
 * API distinguishes them precisely so a screen can.
 */
export function StatTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number | null;
  hint?: string;
}) {
  return (
    <div className="grid gap-0.5 row" data-stat={label}>
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="text-xl font-semibold tracking-tight tabular-nums">
        {value === null ? "—" : typeof value === "number" ? value.toLocaleString() : value}
      </dd>
      {hint ? <p className="text-muted-foreground text-xs">{hint}</p> : null}
    </div>
  );
}

/** A row of them, which is what a dashboard's top actually is. */
export function StatRow({ children }: { children: React.ReactNode }) {
  return (
    <dl className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">{children}</dl>
  );
}
