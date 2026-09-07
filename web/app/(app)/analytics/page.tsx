import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { RangePicker } from "./range-picker";
import { DaySeries } from "@/components/charts/day-series";
import { MagnitudeBars } from "@/components/charts/magnitude-bars";
import { StatRow, StatTile } from "@/components/charts/stat-tile";
import { Refusal } from "@/components/refusal";
import {
  duration,
  percentage,
  readAiAnalytics,
  readConversationAnalytics,
  readOverview,
  type Window,
} from "@/lib/analytics";
import { ApiError } from "@/lib/errors";
import type { AiAnalytics, ConversationAnalytics, Overview } from "@/lib/types";
import { activeWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Analytics" };

/**
 * What the business actually did.
 *
 * Any member may read it — knowing how the inbox is going is not
 * administration — and no figure on this page is computed here. Two
 * totals derived from the same rows the API already counted is two answers
 * to one question, and the one on screen is the one somebody acts on.
 */
export default async function AnalyticsPage({
  searchParams,
}: {
  searchParams: Promise<{ start?: string; end?: string }>;
}) {
  const workspace = await activeWorkspace();

  if (!workspace) redirect("/workspaces");

  const { start, end } = await searchParams;

  const window: Window = {
    start: start ?? null,
    end: end ?? null,
    // The workspace's own zone, so a day on this page is the day the
    // business had rather than one cut on UTC midnight.
    timezone: workspace.timezone,
  };

  let overview: Overview;
  let conversations: ConversationAnalytics;
  let assistant: AiAnalytics;

  try {
    [overview, conversations, assistant] = await Promise.all([
      readOverview(workspace.id, window),
      readConversationAnalytics(workspace.id, window),
      readAiAnalytics(workspace.id, window),
    ]);
  } catch (error) {
    // A backwards range is the person's to fix, and belongs on the picker
    // rather than as a page that failed to load.
    if (
      error instanceof ApiError &&
      (error.code === "invalid_date_range" || error.code === "unknown_timezone")
    ) {
      return (
        <div className="grid gap-6">
          <h1 className="text-2xl font-semibold tracking-tight">Analytics</h1>
          <Refusal state={{ error: error.sentence, code: error.code }} />
          <RangePicker start={start ?? null} end={end ?? null} />
        </div>
      );
    }

    throw error;
  }

  const answered = overview.handled.answered;

  return (
    <div className="grid gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Analytics</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          {workspace.name}, counted in {workspace.timezone}.
        </p>
      </div>

      <RangePicker start={start ?? null} end={end ?? null} />

      <StatRow>
        <StatTile label="Conversations" value={overview.conversations.total} />
        <StatTile
          label="Answered"
          value={answered}
          hint={`${overview.handled.by_agents} by people, ${overview.handled.by_ai} by the assistant`}
        />
        <StatTile
          label="First reply"
          // Null all the way through: nothing answered yet is not the
          // same fact as answered instantly.
          value={duration(overview.average_first_response_seconds)}
          hint={
            overview.average_first_response_seconds === null
              ? "Nothing answered yet"
              : "On average"
          }
        />
        <StatTile
          label="Assistant"
          value={percentage(overview.ai_response_rate)}
          hint="Of answered conversations it spoke in"
        />
      </StatRow>

      <section className="grid gap-3">
        <div>
          <h2 className="text-sm font-medium">Conversations opened</h2>
          <p className="text-muted-foreground text-xs">
            One point per day. Days with none are zero rather than missing.
          </p>
        </div>
        <DaySeries points={conversations.by_day} label="conversations" />
      </section>

      <div className="grid gap-8 lg:grid-cols-2 lg:items-start">
        <section className="grid gap-3">
          <div>
            <h2 className="text-sm font-medium">Where conversations stand</h2>
            <p className="text-muted-foreground text-xs">
              Right now, not over the range.
            </p>
          </div>
          <MagnitudeBars
            rows={[
              { label: "Open", value: overview.conversations.open },
              { label: "Pending", value: overview.conversations.pending },
              { label: "Closed", value: overview.conversations.closed },
              {
                label: "With a person",
                value: overview.conversations.with_a_human,
              },
              { label: "Unassigned", value: overview.conversations.unassigned },
            ]}
            empty="No conversations yet."
          />
        </section>

        <section className="grid gap-3">
          <div>
            <h2 className="text-sm font-medium">What the assistant decided</h2>
            <p className="text-muted-foreground text-xs">
              {percentage(assistant.answer_rate)} of the times it was asked, it
              had something to send.
            </p>
          </div>
          <MagnitudeBars
            rows={[
              {
                label: "Answered",
                value: assistant.decisions.answered,
                hint: "sent",
              },
              {
                label: "Suggested",
                value: assistant.decisions.suggested,
                hint: "drafted",
              },
              {
                label: "Handed over",
                value: assistant.decisions.handoff,
                hint: "left for a person",
              },
              {
                label: "Not attempted",
                value: assistant.decisions.blocked,
                hint: "switched off, or out of allowance",
              },
              { label: "Failed", value: assistant.decisions.failed },
            ]}
            empty="The assistant has not been asked anything yet."
          />
        </section>
      </div>

      <section className="grid gap-3">
        <h2 className="text-sm font-medium">What the assistant cost</h2>
        <StatRow>
          <StatTile label="Input tokens" value={assistant.cost.input_tokens} />
          <StatTile label="Output tokens" value={assistant.cost.output_tokens} />
          <StatTile
            label="Latency"
            value={
              assistant.cost.average_latency_ms === null
                ? null
                : `${Math.round(assistant.cost.average_latency_ms)}ms`
            }
            hint="On average"
          />
          <StatTile
            label="Confidence"
            value={
              assistant.cost.average_confidence === null
                ? null
                : percentage(assistant.cost.average_confidence)
            }
            hint="On average"
          />
        </StatRow>
      </section>
    </div>
  );
}
