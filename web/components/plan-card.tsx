import { Badge } from "@/components/ui/badge";
import { formatMoney } from "@/lib/money";
import { FEATURE_LABEL, LIMIT_LABEL, ceilingLabel, isFree } from "@/lib/plans";
import type { Plan, PlanLimit } from "@/lib/types";

const LIMIT_ORDER: PlanLimit[] = [
  "team_members",
  "whatsapp_numbers",
  "ai_responses_per_month",
  "knowledge_documents",
];

/**
 * One plan, as somebody deciding between them reads it.
 *
 * Every limit on every plan, in the same order, because the API returns
 * them that way for exactly this reason: a comparison needs a row for each
 * limit on each plan, and "not mentioned" would render as a gap where
 * "unlimited" belongs.
 *
 * The price is the string the API sent. `formatMoney` never parses it --
 * see that module for why a plan costing 49 must not become 48.99999.
 */
export function PlanCard({
  plan,
  current,
  children,
}: {
  plan: Plan;
  current?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <div
      data-tier={plan.tier}
      data-current={current ? "" : undefined}
      className="data-current:border-primary grid gap-3 rounded-lg border px-4 py-4"
    >
      <div className="grid gap-1">
        <div className="flex items-center gap-2">
          <h3 className="font-medium">{plan.name}</h3>
          {current ? <Badge variant="secondary">Current</Badge> : null}
        </div>
        <p className="text-muted-foreground text-sm">{plan.description}</p>
      </div>

      <p className="text-2xl font-semibold tracking-tight tabular-nums">
        {isFree(plan) ? (
          "Free"
        ) : (
          <>
            {formatMoney(plan.price, plan.currency)}
            <span className="text-muted-foreground text-sm font-normal">
              {" "}
              a month
            </span>
          </>
        )}
      </p>

      <dl className="grid gap-1 text-sm">
        {LIMIT_ORDER.map((limit) => (
          <div key={limit} className="flex justify-between gap-3">
            <dt className="text-muted-foreground">{LIMIT_LABEL[limit]}</dt>
            {/*
              "Unlimited" spelled out. A blank cell reads as a value the
              page failed to load.
            */}
            <dd className="tabular-nums">{ceilingLabel(plan.limits[limit])}</dd>
          </div>
        ))}
      </dl>

      <ul className="grid gap-1 text-sm">
        {(Object.keys(FEATURE_LABEL) as (keyof typeof FEATURE_LABEL)[]).map(
          (feature) => {
            const included = plan.features.includes(feature);

            return (
              <li
                key={feature}
                className={included ? "" : "text-muted-foreground/60"}
              >
                {/*
                  Every feature on every plan, included or not. A list that
                  only showed what you get makes two plans impossible to
                  compare without counting lines.
                */}
                {included ? "✓" : "—"} {FEATURE_LABEL[feature]}
              </li>
            );
          },
        )}
      </ul>

      {children}
    </div>
  );
}
