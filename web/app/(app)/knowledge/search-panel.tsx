"use client";

import Link from "next/link";
import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { FieldError, FormError } from "@/components/form";
import { SectionHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { searchKnowledge } from "@/lib/knowledge-actions";
import type { FormState } from "@/lib/form-state";

function AskButton() {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" size="sm" disabled={pending}>
      {pending ? "Searching…" : "Search"}
    </Button>
  );
}

/**
 * Ask the knowledge base what the assistant would be given.
 *
 * Submitted rather than searched per keystroke, and that is not laziness:
 * the endpoint is rate limited and every call is an embedding somebody
 * pays for. Debouncing would still fire on a pause mid-word; a button
 * fires when a person has finished their thought.
 *
 * Every match names the document it came from, because a passage with no
 * provenance cannot be acted on -- the whole point of running this before
 * trusting the assistant with a customer is finding the document that
 * needs fixing.
 */
export function SearchPanel({ workspaceId }: { workspaceId: string }) {
  const [state, ask] = useActionState<FormState, FormData>(searchKnowledge, null);

  const result = state?.search;

  return (
    <section className="grid gap-3 panel">
      <SectionHeader
        title="Try a question"
        description="The same retrieval the assistant runs. What comes back is what it would be given."
      />

      <form action={ask} className="flex flex-wrap items-start gap-2">
        <input type="hidden" name="workspace_id" value={workspaceId} />
        <div className="min-w-0 flex-1">
          <Input
            name="query"
            maxLength={1000}
            placeholder="How long do refunds take?"
            aria-label="Search the knowledge base"
            className="h-9"
          />
          <FieldError>{state?.fields?.query}</FieldError>
        </div>
        <AskButton />
      </form>

      <FormError>{state?.error}</FormError>

      {state?.retryAfter ? (
        <p className="text-muted-foreground text-xs">
          Too many searches. Try again in {state.retryAfter} seconds.
        </p>
      ) : null}

      {result ? (
        result.matches.length === 0 ? (
          <p className="text-muted-foreground text-sm" data-testid="search-results">
            Nothing in the knowledge base came close enough. The assistant
            would hand this one to a person.
          </p>
        ) : (
          <ol className="grid gap-2" data-testid="search-results">
            {result.matches.map((match) => (
              <li key={match.chunk_id} className="row grid gap-1">
                <div className="flex items-center gap-2 text-xs">
                  <Link
                    href={`/knowledge/${match.document_id}`}
                    className="underline underline-offset-4"
                  >
                    Open the document
                  </Link>
                  <span className="text-muted-foreground tabular-nums">
                    {match.score.toFixed(2)}
                  </span>
                </div>
                <p className="text-sm">{match.content}</p>
              </li>
            ))}
          </ol>
        )
      ) : null}
    </section>
  );
}
