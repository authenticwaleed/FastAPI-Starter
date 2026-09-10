"use client";

import { useActionState, useState } from "react";

import { FieldError, SubmitButton } from "@/components/form";
import { Refusal } from "@/components/refusal";
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
import { Textarea } from "@/components/ui/textarea";
import { addFaq, addText } from "@/lib/knowledge-actions";
import type { FormState } from "@/lib/form-state";
import type { KnowledgeSource } from "@/lib/types";

/**
 * Knowledge typed rather than uploaded.
 *
 * Two shapes, and they are genuinely two. An FAQ is a question and its
 * answer, and the API keeps them apart because the question is part of
 * what gets embedded -- which is what makes a customer asking it in their
 * own words find the answer. Flattening the pair into prose here would
 * leave this screen inventing a format that then becomes what the
 * assistant retrieves.
 */
export function AddText({
  workspaceId,
  sources,
}: {
  workspaceId: string;
  sources: KnowledgeSource[];
}) {
  const [kind, setKind] = useState<"text" | "faq">("text");
  const [textState, submitText] = useActionState<FormState, FormData>(addText, null);
  const [faqState, submitFaq] = useActionState<FormState, FormData>(addFaq, null);

  const state = kind === "text" ? textState : faqState;

  if (sources.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Write something</h2>
          </CardTitle>
          <CardDescription>
            Add a source first — a document has to belong to one.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const sourcePicker = (
    <div className="grid gap-2">
      <Label htmlFor={`${kind}-source`}>Source</Label>
      <NativeSelect
        id={`${kind}-source`}
        name="knowledge_source_id"
      >
        {sources.map((source) => (
          <option key={source.id} value={source.id}>
            {source.name}
          </option>
        ))}
      </NativeSelect>
    </div>
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Write something</h2>
        </CardTitle>
        <CardDescription>
          A policy, a page of notes, or one question and its answer.
        </CardDescription>
      </CardHeader>

      <CardContent className="grid gap-4">
        <div className="flex gap-4 text-sm" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={kind === "text"}
            onClick={() => setKind("text")}
            className={
              kind === "text"
                ? "font-medium underline underline-offset-4"
                : "text-muted-foreground underline-offset-4 hover:underline"
            }
          >
            Text
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={kind === "faq"}
            onClick={() => setKind("faq")}
            className={
              kind === "faq"
                ? "font-medium underline underline-offset-4"
                : "text-muted-foreground underline-offset-4 hover:underline"
            }
          >
            Question and answer
          </button>
        </div>

        <Refusal state={state} />

        {kind === "text" ? (
          <form action={submitText} className="grid gap-4">
            <input type="hidden" name="workspace_id" value={workspaceId} />
            {sourcePicker}

            <div className="grid gap-2">
              <Label htmlFor="text-title">Title</Label>
              <Input id="text-title" name="title" maxLength={255} required />
              <FieldError>{textState?.fields?.title}</FieldError>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="text-content">Content</Label>
              {/*
                No maximum. A returns policy is a page and a catalogue is
                not, and the API deliberately takes both -- a business that
                pastes a long one should get a slow request rather than a
                rejection with a number in it that means nothing to them.
              */}
              <Textarea id="text-content" name="content" rows={8} required />
              <FieldError>{textState?.fields?.content}</FieldError>
            </div>

            <SubmitButton className="w-fit">Add</SubmitButton>
          </form>
        ) : (
          <form action={submitFaq} className="grid gap-4">
            <input type="hidden" name="workspace_id" value={workspaceId} />
            {sourcePicker}

            <div className="grid gap-2">
              <Label htmlFor="faq-question">Question</Label>
              <Input
                id="faq-question"
                name="question"
                maxLength={500}
                placeholder="How long do refunds take?"
                required
              />
              <FieldError>{faqState?.fields?.question}</FieldError>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="faq-answer">Answer</Label>
              <Textarea id="faq-answer" name="answer" rows={5} required />
              <FieldError>{faqState?.fields?.answer}</FieldError>
            </div>

            <SubmitButton className="w-fit">Add</SubmitButton>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
