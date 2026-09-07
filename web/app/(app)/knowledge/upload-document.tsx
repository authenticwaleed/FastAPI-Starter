"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { sentenceFor, type ErrorBody } from "@/lib/errors";
import {
  ACCEPT_ATTRIBUTE,
  MAX_FILE_LABEL,
  isTooLarge,
  readableSize,
} from "@/lib/knowledge-limits";
import type { KnowledgeSource } from "@/lib/types";

type Upload =
  | { state: "idle" }
  | { state: "sending"; name: string; percent: number }
  | { state: "failed"; message: string }
  | { state: "done"; title: string };

/**
 * Upload a file, and say how far it has got.
 *
 * `XMLHttpRequest` rather than `fetch`, and a client component rather than
 * a server action, for one reason each. Progress needs upload events,
 * which `fetch` still does not give and a server action cannot forward at
 * all. And a server action would have to carry the whole file through
 * Next's own body limit, which defaults to a megabyte -- a tenth of what
 * the API accepts.
 *
 * So the file goes straight to the relay, which attaches the bearer token
 * from a cookie the page cannot read. Nothing about that is weaker than
 * the rest of the client; it is the same door with a different body.
 */
export function UploadDocument({
  workspaceId,
  sources,
}: {
  workspaceId: string;
  sources: KnowledgeSource[];
}) {
  const [upload, setUpload] = useState<Upload>({ state: "idle" });
  const input = useRef<HTMLInputElement>(null);
  const router = useRouter();

  function send(file: File, sourceId: string) {
    // Refused here as well as at the API, so somebody with a 40MB scan
    // finds out now rather than after four minutes of uploading.
    if (isTooLarge(file)) {
      setUpload({
        state: "failed",
        message: `That file is ${readableSize(file.size)}. The limit is ${MAX_FILE_LABEL}.`,
      });

      return;
    }

    const body = new FormData();

    body.set("knowledge_source_id", sourceId);
    body.set("file", file);

    const request = new XMLHttpRequest();

    request.open("POST", `/api/workspaces/${workspaceId}/knowledge/documents/upload`);

    request.upload.addEventListener("progress", (event) => {
      if (!event.lengthComputable) return;

      setUpload({
        state: "sending",
        name: file.name,
        percent: Math.round((event.loaded / event.total) * 100),
      });
    });

    request.addEventListener("load", () => {
      if (request.status >= 200 && request.status < 300) {
        const document = JSON.parse(request.responseText) as { title: string };

        setUpload({ state: "done", title: document.title });
        if (input.current) input.current.value = "";

        // The list is a server component, so this is what redraws it.
        router.refresh();

        return;
      }

      // One sentence, from the same map every other screen uses. The two
      // that matter here are 415 -- a file nothing can open -- and 422,
      // which is a file that opened and had no text in it. A scan is the
      // ordinary cause of the second, and they must not read alike.
      let body: Partial<ErrorBody> = {};

      try {
        body = JSON.parse(request.responseText) as Partial<ErrorBody>;
      } catch {
        // Not the envelope. The status is all there is.
      }

      setUpload({
        state: "failed",
        message: sentenceFor(body.code ?? "http_error", body.detail),
      });
    });

    request.addEventListener("error", () => {
      setUpload({
        state: "failed",
        message: "The upload did not get through. Try again.",
      });
    });

    setUpload({ state: "sending", name: file.name, percent: 0 });
    request.send(body);
  }

  if (sources.length === 0) {
    return (
      <p className="text-muted-foreground text-sm">
        Add a source first — a document has to belong to one.
      </p>
    );
  }

  return (
    <div className="grid gap-3">
      <form
        className="grid gap-3"
        onSubmit={(event) => {
          event.preventDefault();

          const form = new FormData(event.currentTarget);
          const file = form.get("file");

          if (file instanceof File && file.size > 0) {
            send(file, String(form.get("knowledge_source_id") ?? ""));
          }
        }}
      >
        <div className="grid gap-2">
          <Label htmlFor="upload-source">Source</Label>
          <select
            id="upload-source"
            name="knowledge_source_id"
            className="border-input bg-background h-9 rounded-md border px-2 text-sm"
          >
            {sources.map((source) => (
              <option key={source.id} value={source.id}>
                {source.name}
              </option>
            ))}
          </select>
        </div>

        <div className="grid gap-2">
          <Label htmlFor="upload-file">File</Label>
          <input
            ref={input}
            id="upload-file"
            name="file"
            type="file"
            accept={ACCEPT_ATTRIBUTE}
            required
            className="text-sm file:mr-3 file:rounded-md file:border file:bg-transparent file:px-3 file:py-1.5 file:text-sm"
          />
          <p className="text-muted-foreground text-xs">
            PDF or plain text, up to {MAX_FILE_LABEL}.
          </p>
        </div>

        <Button
          type="submit"
          size="sm"
          className="w-fit"
          disabled={upload.state === "sending"}
        >
          Upload
        </Button>
      </form>

      {upload.state === "sending" ? (
        <div className="grid gap-1" data-testid="upload-progress">
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground truncate">{upload.name}</span>
            <span className="tabular-nums">{upload.percent}%</span>
          </div>
          {/*
            A real progress element rather than a spinner: the API takes
            ten megabytes, and "something is happening" is not enough
            information when the something can last a minute.
          */}
          <progress
            value={upload.percent}
            max={100}
            aria-label={`Uploading ${upload.name}`}
            className="h-1.5 w-full"
          />
        </div>
      ) : null}

      {upload.state === "failed" ? (
        <p role="alert" className="text-destructive text-sm">
          {upload.message}
        </p>
      ) : null}

      {upload.state === "done" ? (
        <p role="status" className="text-muted-foreground text-sm">
          Added {upload.title}. It is being processed.
        </p>
      ) : null}
    </div>
  );
}
