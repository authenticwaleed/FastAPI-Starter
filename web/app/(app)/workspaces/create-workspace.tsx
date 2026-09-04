"use client";

import { useActionState, useState } from "react";

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
import { createWorkspace } from "@/lib/workspace-actions";
import type { FormState } from "@/lib/form-state";

/**
 * Slug suggested from the name, and still editable.
 *
 * Suggested rather than derived, because the API's rule -- lowercase words
 * joined by single hyphens -- has more than one reasonable answer for
 * "Ada & Co.", and the person naming their own business should be the one
 * to pick. Typing in the slug field stops the suggestion overwriting it.
 */
function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 63);
}

export function CreateWorkspace() {
  const [state, action] = useActionState<FormState, FormData>(createWorkspace, null);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);

  const shown = slugTouched ? slug : slugify(name);

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>New workspace</h2>
        </CardTitle>
        <CardDescription>
          You become its owner. The address cannot be changed afterwards —
          it ends up in links, so moving it would break the ones that exist.
        </CardDescription>
      </CardHeader>

      <CardContent>
        <form action={action} className="grid max-w-md gap-4">
          <FormError>{state?.error}</FormError>

          <div className="grid gap-2">
            <Label htmlFor="ws-name">Name</Label>
            <Input
              id="ws-name"
              name="name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Acme Fashion"
              maxLength={100}
              required
            />
            <FieldError>{state?.fields?.name}</FieldError>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="ws-slug">Address</Label>
            <Input
              id="ws-slug"
              name="slug"
              value={shown}
              onChange={(event) => {
                setSlugTouched(true);
                setSlug(event.target.value);
              }}
              placeholder="acme-fashion"
              pattern="[a-z0-9]+(-[a-z0-9]+)*"
              minLength={3}
              maxLength={63}
              required
            />
            <FieldError>{state?.fields?.slug}</FieldError>
            <p className="text-muted-foreground text-xs">
              Lowercase words joined by hyphens, three characters or more.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-2">
              <Label htmlFor="ws-timezone">Timezone</Label>
              <Input
                id="ws-timezone"
                name="timezone"
                defaultValue="UTC"
                placeholder="Asia/Karachi"
                maxLength={64}
              />
              <FieldError>{state?.fields?.timezone}</FieldError>
              <p className="text-muted-foreground text-xs">
                Every report is bucketed in this zone.
              </p>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="ws-currency">Currency</Label>
              <Input
                id="ws-currency"
                name="default_currency"
                defaultValue="USD"
                maxLength={3}
                className="uppercase"
              />
              <FieldError>{state?.fields?.default_currency}</FieldError>
              <p className="text-muted-foreground text-xs">
                Three-letter ISO code.
              </p>
            </div>
          </div>

          <SubmitButton className="w-fit">Create workspace</SubmitButton>
        </form>
      </CardContent>
    </Card>
  );
}
