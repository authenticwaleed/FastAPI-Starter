/**
 * A handful of counts, compared.
 *
 * Horizontal bars because the labels are words rather than dates, and a
 * word reads better beside a bar than rotated under one.
 *
 * One hue throughout, and deliberately: these are magnitudes of the same
 * measure, not five identities to track across charts. A five-colour
 * palette here would imply the colours meant something and would then have
 * to survive a colour-vision check it does not need to take.
 *
 * Every row is labelled with its own number, which is the secondary
 * encoding that makes the bar an illustration rather than the only way to
 * read the value.
 */
export function MagnitudeBars({
  rows,
  empty = "Nothing recorded in this range.",
}: {
  rows: { label: string; value: number; hint?: string }[];
  empty?: string;
}) {
  const peak = Math.max(...rows.map((row) => row.value), 1);
  const anything = rows.some((row) => row.value > 0);

  if (!anything) {
    return (
      <p className="text-muted-foreground rounded-md border border-dashed px-4 py-6 text-center text-sm">
        {empty}
      </p>
    );
  }

  return (
    <ul className="grid gap-2">
      {rows.map((row) => (
        <li key={row.label} className="grid gap-1" data-row={row.label}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span>
              {row.label}
              {row.hint ? (
                <span className="text-muted-foreground"> · {row.hint}</span>
              ) : null}
            </span>
            <span className="tabular-nums">{row.value.toLocaleString()}</span>
          </div>

          <div className="bg-muted h-1.5 w-full overflow-hidden rounded-full">
            {/*
              Anchored to the baseline and rounded only at the data end,
              so a short bar still reads as a bar rather than a pill
              floating in the track.
            */}
            <div
              className="bg-data h-full rounded-r-full"
              style={{ width: `${Math.max((row.value / peak) * 100, row.value > 0 ? 2 : 0)}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}
