"use client";

import { useId, useState } from "react";

import type { DayPoint } from "@/lib/types";

/**
 * One count, over days.
 *
 * A single series, so there is no legend: the title names it, and a legend
 * box for one thing is furniture. One hue, one axis — never a second scale
 * pinned to the right, which is the mistake that makes two unrelated
 * measures look correlated.
 *
 * Every number comes from the API. Nothing here totals, averages or
 * back-fills: the API already returns days with nothing in them as zero,
 * which is why gaps in the line are impossible rather than handled.
 *
 * Plain SVG. A charting library for one line would be a dependency, a
 * bundle, and a second set of colour rules to keep in step with the ones
 * in globals.css.
 */
export function DaySeries({
  points,
  label,
}: {
  points: DayPoint[];
  label: string;
}) {
  const clipId = useId();
  const [hovered, setHovered] = useState<number | null>(null);

  if (points.length === 0) {
    return (
      <p className="text-muted-foreground rounded-md border border-dashed px-4 py-8 text-center text-sm">
        Nothing in this range.
      </p>
    );
  }

  // Room in the viewBox for the outermost labels, so nothing is clipped.
  const width = 720;
  const height = 180;
  const pad = { top: 16, right: 12, bottom: 24, left: 36 };

  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;

  const counts = points.map((point) => point.count);

  // Two different numbers, and conflating them was a real bug: `highest`
  // is what the data reaches, `peak` is what the axis is drawn against.
  // They differ only when nothing happened at all -- and then the floor of
  // 1 keeps the scale from dividing by zero while `highest` stays 0, so
  // looking a value up by it still finds a day that exists.
  const highest = Math.max(...counts);
  const peak = Math.max(highest, 1);

  // Ticks the axis actually reaches: every label names a value on the
  // scale rather than a round number the data never gets to.
  const ticks = [0, Math.round(peak / 2), peak].filter(
    (value, index, all) => all.indexOf(value) === index,
  );

  const x = (index: number) =>
    pad.left +
    (points.length === 1 ? plotWidth / 2 : (index / (points.length - 1)) * plotWidth);
  const y = (count: number) => pad.top + plotHeight - (count / peak) * plotHeight;

  const line = points
    .map((point, index) => `${index === 0 ? "M" : "L"}${x(index)},${y(point.count)}`)
    .join(" ");

  const area =
    `${line} L${x(points.length - 1)},${pad.top + plotHeight}` +
    ` L${x(0)},${pad.top + plotHeight} Z`;

  const quiet = highest === 0;
  const busiest = counts.indexOf(highest);
  const shown = hovered ?? busiest;
  const point = points[shown];

  return (
    <figure className="grid gap-2">
      <div className="relative">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="w-full"
          role="img"
          aria-label={
            quiet
              ? `${label} by day. None in this range.`
              : `${label} by day. Busiest was ${highest} on ${points[busiest].day}.`
          }
          onMouseLeave={() => setHovered(null)}
        >
          <defs>
            <clipPath id={clipId}>
              <rect
                x={pad.left}
                y={pad.top}
                width={plotWidth}
                height={plotHeight}
                fill="#000000"
              />
            </clipPath>
          </defs>

          {/* Recessive: the grid is a reference, not a subject. */}
          {ticks.map((value) => (
            <g key={value}>
              <line
                x1={pad.left}
                x2={width - pad.right}
                y1={y(value)}
                y2={y(value)}
                stroke="var(--color-grid)"
                strokeWidth={1}
              />
              <text
                x={pad.left - 8}
                y={y(value) + 4}
                textAnchor="end"
                className="fill-muted-foreground text-2xs tabular-nums"
              >
                {value}
              </text>
            </g>
          ))}

          <path d={area} fill="var(--color-data-soft)" clipPath={`url(#${clipId})`} />
          <path
            d={line}
            fill="none"
            stroke="var(--color-data)"
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
          />

          {/* The marker sits on a surface ring so it reads over the line. */}
          <circle
            cx={x(shown)}
            cy={y(point.count)}
            r={4}
            fill="var(--color-data)"
            stroke="var(--color-background)"
            strokeWidth={2}
          />

          {/*
            Hit targets wider than the marks, so a value can be reached
            without landing exactly on a four-pixel dot.
          */}
          {points.map((each, index) => (
            <rect
              key={each.day}
              x={x(index) - plotWidth / points.length / 2}
              y={pad.top}
              width={plotWidth / points.length}
              height={plotHeight}
              fill="transparent"
              onMouseEnter={() => setHovered(index)}
            />
          ))}

          {/* Two labels, not one per point: the ends of the range. */}
          <text
            x={pad.left}
            y={height - 6}
            className="fill-muted-foreground text-2xs"
          >
            {points[0].day}
          </text>
          {points.length > 1 ? (
            <text
              x={width - pad.right}
              y={height - 6}
              textAnchor="end"
              className="fill-muted-foreground text-2xs"
            >
              {points[points.length - 1].day}
            </text>
          ) : null}
        </svg>
      </div>

      <figcaption className="text-muted-foreground text-xs tabular-nums">
        {/*
          Text in text tokens, never the series colour. The mark carries
          identity; the words carry the reading.
        */}
        <span className="text-foreground font-medium">{point.count}</span> {label}{" "}
        on {point.day}
        {hovered === null && !quiet ? " — the busiest day in this range" : ""}
      </figcaption>
    </figure>
  );
}
