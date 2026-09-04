"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { FormError } from "@/components/form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { requestAiReply } from "@/lib/conversation-actions";
import type { FormState } from "@/lib/form-state";
import type { AiDecision, AiResponseLog, Conversation } from "@/lib/types";

/** The assistant's own vocabulary, in words somebody would say. */
const DECISION: Record<AiDecision, string> = {
  answered: "Sent to the customer",
  suggested: "Drafted for you",
  handoff: "Left for a person",
  blocked: "Not attempted",
};

/**
 * Why it declined, when there is a reason.
 *
 * `plan_limit` is the one worth spelling out. Running out of the monthly
 * allowance does not raise at the API -- it records a blocked decision and
 * the customer's message still arrives unanswered -- so without this the
 * thread would show a message nobody replied to and nothing saying why.
 */
const REASON: Record<string, string> = {
  no_knowledge: "Nothing in the knowledge base covered this.",
  low_confidence: "It was not confident enough in its answer.",
  cannot_answer: "It could not answer this one.",
  ai_disabled: "The assistant is switched off for this conversation.",
  plan_limit: "This month's assistant allowance has run out.",
  provider_error: "The model could not be reached.",
};

function AskButton() {
  const { pending } = useFormStatus();

  // One at a time. This costs money and is rate limited, so a second press
  // while the first is running buys nothing but another charge.
  return (
    <Button type="submit" size="sm" variant="outline" disabled={pending}>
      {pending ? "Thinking…" : "Draft a reply"}
    </Button>
  );
}

function Draft({ text }: { text: string }) {
  return (
    <div className="grid gap-1.5">
      <div className="flex items-center gap-2">
        <Badge variant="secondary">Draft</Badge>
        <span className="text-muted-foreground text-xs">Not sent</span>
      </div>
      {/*
        Plainly a draft until a person sends it: it is labelled, it is not
        in the thread, and it is selectable so it can be copied into the
        composer and edited. Rendering it among the messages would make a
        suggestion look like something the customer has already received.
      */}
      <p className="bg-muted rounded-md px-3 py-2 text-sm whitespace-pre-wrap select-all">
        {text}
      </p>
    </div>
  );
}

export function AssistantPanel({
  workspaceId,
  conversation,
  history,
  canWrite,
}: {
  workspaceId: string;
  conversation: Conversation;
  history: AiResponseLog[];
  canWrite: boolean;
}) {
  const [state, ask] = useActionState<FormState, FormData>(requestAiReply, null);

  const reply = state?.reply;
  const latest = history[0];

  return (
    <section className="grid gap-3 rounded-md border px-3 py-3">
      <h2 className="text-sm font-medium">Assistant</h2>

      <FormError>{state?.error}</FormError>

      {state?.retryAfter ? (
        <p className="text-muted-foreground text-xs">
          Try again in {state.retryAfter} seconds.
        </p>
      ) : null}

      {reply ? (
        <div className="grid gap-2">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Badge variant="outline">{DECISION[reply.decision]}</Badge>
            {reply.confidence !== null ? (
              <span className="text-muted-foreground tabular-nums">
                {Math.round(reply.confidence * 100)}% confident
              </span>
            ) : null}
          </div>

          {/*
            Branch on the decision, never on the text: a reply with no text
            is the ordinary shape of a handoff, and checking text first
            reads "a person should take this" as an empty answer.
          */}
          {reply.decision === "suggested" && reply.text ? (
            <Draft text={reply.text} />
          ) : reply.decision === "answered" ? (
            <p className="text-muted-foreground text-sm">
              Sent. It is in the thread.
            </p>
          ) : (
            <p className="text-muted-foreground text-sm">
              {(reply.reason && REASON[reply.reason]) ??
                "It did not answer this one."}
            </p>
          )}

          {reply.sources.length > 0 ? (
            <p className="text-muted-foreground text-xs">
              Grounded in {reply.sources.length} passage
              {reply.sources.length === 1 ? "" : "s"} from your knowledge base.
            </p>
          ) : null}
        </div>
      ) : latest ? (
        <div className="grid gap-2">
          <div className="flex items-center gap-2 text-xs">
            <Badge variant="outline">{DECISION[latest.decision]}</Badge>
            <span className="text-muted-foreground">last time</span>
          </div>
          {latest.decision === "suggested" && latest.reply_text ? (
            <Draft text={latest.reply_text} />
          ) : latest.reason ? (
            <p className="text-muted-foreground text-sm">
              {REASON[latest.reason] ?? latest.reason}
            </p>
          ) : null}
        </div>
      ) : (
        <p className="text-muted-foreground text-sm">
          The assistant has not looked at this conversation yet.
        </p>
      )}

      {canWrite && conversation.ai_mode !== "disabled" ? (
        <form action={ask}>
          <input type="hidden" name="workspace_id" value={workspaceId} />
          <input type="hidden" name="conversation_id" value={conversation.id} />
          <AskButton />
        </form>
      ) : conversation.ai_mode === "disabled" ? (
        <p className="text-muted-foreground text-xs">
          Switched off for this conversation. Hand it back to turn it on.
        </p>
      ) : null}

      {history.length > 1 ? (
        <details className="text-xs">
          <summary className="text-muted-foreground cursor-pointer">
            Earlier decisions ({history.length})
          </summary>
          <ol className="mt-2 grid gap-1.5">
            {history.map((entry) => (
              <li key={entry.id} className="text-muted-foreground">
                {DECISION[entry.decision]}
                {entry.reason ? ` · ${REASON[entry.reason] ?? entry.reason}` : ""}
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </section>
  );
}
