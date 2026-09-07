"use client";

import { useActionState, useState } from "react";
import { useFormStatus } from "react-dom";

import { FieldError, SubmitButton } from "@/components/form";
import { Refusal } from "@/components/refusal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { connectWhatsApp, disconnectWhatsApp } from "@/lib/integration-actions";
import type { FormState } from "@/lib/form-state";
import type { WhatsAppAccount } from "@/lib/types";

function DisconnectButton() {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" variant="destructive" size="sm" disabled={pending}>
      Disconnect this number
    </Button>
  );
}

/**
 * The number customers actually message.
 *
 * There is no token field when a number is connected, and that is not a
 * simplification: the API never returns the access token, encrypted or
 * otherwise, so there is nothing to pre-fill a field with. Connected or
 * not is the whole of the state anybody can see. Changing the token means
 * disconnecting and connecting again, which the copy says.
 */
export function WhatsAppPanel({
  workspaceId,
  account,
  canManage,
}: {
  workspaceId: string;
  account: WhatsAppAccount | null;
  canManage: boolean;
}) {
  const [connectState, connect] = useActionState<FormState, FormData>(
    connectWhatsApp,
    null,
  );
  const [removeState, remove] = useActionState<FormState, FormData>(
    disconnectWhatsApp,
    null,
  );
  const [confirming, setConfirming] = useState(false);

  return (
    <Card data-testid="whatsapp-panel">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <h2>WhatsApp</h2>
          <Badge variant={account ? "default" : "outline"}>
            {account ? "Connected" : "Not connected"}
          </Badge>
        </CardTitle>
        <CardDescription>
          The number your customers message. Without one, replies are written
          here and stay queued.
        </CardDescription>
      </CardHeader>

      <CardContent className="grid gap-4">
        {account ? (
          <>
            <dl className="grid gap-1 text-sm">
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Number</dt>
                <dd className="font-mono">{account.phone_number}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Provider</dt>
                <dd>{account.provider}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Connected</dt>
                <dd>
                  {new Date(account.connected_at).toLocaleDateString(undefined, {
                    dateStyle: "medium",
                  })}
                </dd>
              </div>
            </dl>

            <p className="text-muted-foreground text-xs">
              The access token is never shown again, here or anywhere. To
              change it, disconnect and connect the number afresh.
            </p>

            {canManage ? (
              <>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="w-fit"
                  onClick={() => setConfirming(!confirming)}
                >
                  {confirming ? "Cancel" : "Disconnect"}
                </Button>

                {confirming ? (
                  <form action={remove} className="grid gap-2 border-t pt-3">
                    <input type="hidden" name="workspace_id" value={workspaceId} />
                    <input
                      type="hidden"
                      name="phone_number"
                      value={account.phone_number}
                    />

                    <Refusal state={removeState} />

                    {/*
                      What stops working, said before the button. Messages
                      already in the inbox stay; nothing new arrives and
                      nothing goes out.
                    */}
                    <p className="text-muted-foreground text-sm">
                      New messages stop arriving and replies stop going out.
                      Everything already in the inbox stays exactly as it is,
                      and connecting a number again resumes both.
                    </p>

                    <Label htmlFor="wa-confirm" className="text-xs">
                      Type <span className="font-mono">{account.phone_number}</span>{" "}
                      to confirm
                    </Label>
                    <Input
                      id="wa-confirm"
                      name="confirm"
                      autoComplete="off"
                      className="h-8 font-mono"
                      required
                    />
                    <DisconnectButton />
                  </form>
                ) : null}
              </>
            ) : null}
          </>
        ) : canManage ? (
          <form action={connect} className="grid gap-4">
            <input type="hidden" name="workspace_id" value={workspaceId} />

            <Refusal state={connectState} />

            <div className="grid gap-2">
              <Label htmlFor="phone_number">Phone number</Label>
              <Input
                id="phone_number"
                name="phone_number"
                type="tel"
                placeholder="+92 300 1234567"
                required
              />
              <FieldError>{connectState?.fields?.phone_number}</FieldError>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="external_phone_number_id">Phone number ID</Label>
              <Input
                id="external_phone_number_id"
                name="external_phone_number_id"
                maxLength={64}
                className="font-mono"
                required
              />
              <p className="text-muted-foreground text-xs">
                From the WhatsApp Business account, not the number itself.
              </p>
              <FieldError>
                {connectState?.fields?.external_phone_number_id}
              </FieldError>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="access_token">Access token</Label>
              <Input
                id="access_token"
                name="access_token"
                type="password"
                autoComplete="off"
                maxLength={1024}
                required
              />
              <p className="text-muted-foreground text-xs">
                Encrypted before it is stored, and never returned by anything
                afterwards.
              </p>
              <FieldError>{connectState?.fields?.access_token}</FieldError>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="external_business_account_id">
                Business account ID (optional)
              </Label>
              <Input
                id="external_business_account_id"
                name="external_business_account_id"
                maxLength={64}
                className="font-mono"
              />
            </div>

            <SubmitButton className="w-fit">Connect</SubmitButton>
          </form>
        ) : (
          <p className="text-muted-foreground text-sm">
            Only an owner or an admin can connect a number.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
