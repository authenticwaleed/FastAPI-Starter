"use client";

import Link from "next/link";
import { useActionState, useState } from "react";
import { useFormStatus } from "react-dom";

import { FormError } from "@/components/form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { deleteSource } from "@/lib/knowledge-actions";
import type { FormState } from "@/lib/form-state";
import type { KnowledgeSource } from "@/lib/types";

function DeleteButton() {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" variant="destructive" size="sm" disabled={pending}>
      Delete this source
    </Button>
  );
}

/**
 * The groupings, and what deleting one costs.
 *
 * The API deletes for real -- the source, its documents, and every passage
 * retrievable from them. Knowledge a business has withdrawn has to stop
 * being able to appear in an answer to one of its customers, so this is
 * right; what would be wrong is a button that did not say so.
 */
export function SourceList({
  workspaceId,
  sources,
  activeSourceId,
  canManage,
}: {
  workspaceId: string;
  sources: KnowledgeSource[];
  activeSourceId: string | null;
  canManage: boolean;
}) {
  const [state, remove] = useActionState<FormState, FormData>(deleteSource, null);
  const [confirming, setConfirming] = useState<string | null>(null);

  if (sources.length === 0) {
    return (
      <section className="grid gap-3">
        <h2 className="text-sm font-medium">Sources</h2>
        <p className="text-muted-foreground rounded-md border border-dashed px-4 py-6 text-center text-sm">
          None yet. A source is a grouping — “our returns policy”, “the autumn
          catalogue” — and every document belongs to one.
        </p>
      </section>
    );
  }

  return (
    <section className="grid gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-sm font-medium">Sources</h2>
        {activeSourceId ? (
          <Link href="/knowledge" className="text-xs underline underline-offset-4">
            Show all documents
          </Link>
        ) : null}
      </div>

      <FormError>{state?.error}</FormError>

      <ul className="grid gap-2" data-testid="source-list">
        {sources.map((source) => (
          <li
            key={source.id}
            className="grid gap-2 rounded-md border px-3 py-2.5"
            data-source-type={source.source_type}
          >
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <Link
                href={`/knowledge?source=${source.id}`}
                className="text-sm font-medium underline-offset-4 hover:underline"
              >
                {source.name}
              </Link>
              <Badge variant="secondary">{source.source_type}</Badge>
              {source.id === activeSourceId ? (
                <Badge variant="outline">Showing</Badge>
              ) : null}

              {canManage ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="ml-auto"
                  onClick={() =>
                    setConfirming(confirming === source.id ? null : source.id)
                  }
                >
                  {confirming === source.id ? "Cancel" : "Delete"}
                </Button>
              ) : null}
            </div>

            {confirming === source.id ? (
              <form action={remove} className="grid gap-2 border-t pt-2">
                <input type="hidden" name="workspace_id" value={workspaceId} />
                <input type="hidden" name="source_id" value={source.id} />
                <input type="hidden" name="name" value={source.name} />

                <p className="text-muted-foreground text-xs">
                  This deletes the source, every document in it, and every
                  passage the assistant could retrieve from them. It is not
                  recoverable.
                </p>

                <Label htmlFor={`confirm-${source.id}`} className="text-xs">
                  Type <span className="font-mono">{source.name}</span> to confirm
                </Label>
                <Input
                  id={`confirm-${source.id}`}
                  name="confirm"
                  autoComplete="off"
                  className="h-8"
                  required
                />
                <DeleteButton />
              </form>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
