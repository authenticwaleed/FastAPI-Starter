import type { Metadata } from "next";

import { MagnitudeBars } from "@/components/charts/magnitude-bars";
import { StatRow, StatTile } from "@/components/charts/stat-tile";
import { ConsoleHeading } from "@/components/console/heading";
import { consoleRefusal } from "@/components/console/refusal";
import { DaysPicker, windowOf } from "../days-picker";
import { SectionHeader } from "@/components/page-header";
import { readAiSpend } from "@/lib/platform";
import type { AdminAiSpend } from "@/lib/types";

export const metadata: Metadata = { title: "Assistant spend" };

/**
 * What the assistant cost across every tenant.
 *
 * In tokens rather than money, which is the honest unit: what a token
 * costs is a contract with a model provider, it changes without this
 * application being redeployed, and it differs per model. A dollar figure
 * computed here would look authoritative and be wrong within a quarter.
 *
 * Tokens per reply is the figure that moves when somebody grows a prompt,
 * and it moves before the bill does — so it is worked out from two
 * numbers the API returned rather than being a number of its own. That is
 * arithmetic on one response, not a total this client has decided to
 * keep: nothing is aggregated across requests here.
 */
function perReply(tokens: number | null, replies: number): string | null {
  if (tokens === null || replies === 0) return null;

  return Math.round(tokens / replies).toLocaleString();
}

export default async function ConsoleAiSpendPage({
  searchParams,
}: {
  searchParams: Promise<{ days?: string }>;
}) {
  const days = windowOf((await searchParams).days);

  let spend: AdminAiSpend;

  try {
    spend = await readAiSpend({ days });
  } catch (error) {
    return consoleRefusal(error, {
      title: "Assistant spend",
      missing: "Nothing to report.",
    });
  }

  const models = Object.entries(spend.by_model);

  return (
    <div className="grid gap-8">
      <ConsoleHeading
        title="Assistant spend"
        back={{ href: "/console/analytics", label: "Analytics" }}
        description="In tokens. What they cost is a contract with a model provider and changes without this being redeployed."
      />

      <DaysPicker path="/console/analytics/ai" days={days} />

      <StatRow>
        <StatTile label="Replies" value={spend.replies} hint={`Over ${spend.days} days`} />
        <StatTile label="Input tokens" value={spend.input_tokens} />
        <StatTile label="Output tokens" value={spend.output_tokens} />
        <StatTile
          label="Output per reply"
          value={perReply(spend.output_tokens, spend.replies)}
          hint="What moves when a prompt grows"
        />
      </StatRow>

      <StatRow>
        <StatTile
          label="Latency"
          value={
            spend.average_latency_ms === null
              ? null
              : `${Math.round(spend.average_latency_ms)}ms`
          }
          hint="On average"
        />
      </StatRow>

      <section className="grid gap-3">
        <div>
          <SectionHeader title="Replies by model" />
          <p className="text-muted-foreground text-xs">
            {/*
              What a migration between two models looks like from here --
              including the one somebody changed in configuration and
              forgot to mention.
            */}
            Two models with traffic is either a migration or a surprise.
          </p>
        </div>
        <MagnitudeBars
          rows={models.map(([model, replies]) => ({ label: model, value: replies }))}
          empty="The assistant has not been asked anything."
        />
      </section>
    </div>
  );
}
