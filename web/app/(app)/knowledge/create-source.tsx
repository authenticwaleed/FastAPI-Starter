"use client";

import { useActionState } from "react";

import { FieldError, FormError, SubmitButton } from "@/components/form";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { createSource } from "@/lib/knowledge-actions";
import type { FormState } from "@/lib/form-state";

/**
 * A place knowledge comes from.
 *
 * The type describes what will go in it and does not restrict what can --
 * that is the API's choice, and a good one: a source named `file` holding
 * text somebody typed is a labelling mistake rather than a corrupt state,
 * and enforcing it would mean this screen had to know which button created
 * which source.
 */
export function CreateSource({ workspaceId }: { workspaceId: string }) {
  const [state, action] = useActionState<FormState, FormData>(createSource, null);

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Add a source</h2>
        </CardTitle>
        <CardDescription>
          A grouping for related documents — “our returns policy”, “the autumn
          catalogue”. Deleting one takes its documents with it.
        </CardDescription>
      </CardHeader>

      <CardContent>
        <form action={action} className="grid max-w-md gap-4">
          <input type="hidden" name="workspace_id" value={workspaceId} />

          <FormError>{state?.error}</FormError>

          {state?.done ? (
            <p className="text-muted-foreground text-sm" role="status">
              Added.
            </p>
          ) : null}

          <div className="grid gap-2">
            <Label htmlFor="source-name">Name</Label>
            <Input
              id="source-name"
              name="name"
              maxLength={150}
              placeholder="Returns policy"
              required
            />
            <FieldError>{state?.fields?.name}</FieldError>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="source-type">Kind</Label>
            <NativeSelect
              id="source-type"
              name="source_type"
              defaultValue="text"
            >
              <option value="text">Text — typed or pasted</option>
              <option value="file">File — uploaded PDFs or text</option>
              <option value="manual_faq">FAQ — questions and answers</option>
            </NativeSelect>
            <p className="text-muted-foreground text-xs">
              A label for your own sorting. It does not restrict what you can
              put in the source.
            </p>
          </div>

          <SubmitButton className="w-fit">Add source</SubmitButton>
        </form>
      </CardContent>
    </Card>
  );
}
