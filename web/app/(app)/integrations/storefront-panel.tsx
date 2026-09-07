"use client";

import Link from "next/link";
import { useActionState, useEffect, useState } from "react";
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
import {
  beginInstall,
  disconnectStorefront,
  syncStorefront,
} from "@/lib/integration-actions";
import type { FormState } from "@/lib/form-state";
import { STOREFRONT_LABEL } from "@/lib/labels";
import type { Storefront, StorefrontProvider } from "@/lib/types";

function Pending({ children, destructive }: { children: string; destructive?: boolean }) {
  const { pending } = useFormStatus();

  return (
    <Button
      type="submit"
      size="sm"
      variant={destructive ? "destructive" : "outline"}
      disabled={pending}
    >
      {children}
    </Button>
  );
}

/**
 * One connected shop, or a way to connect one.
 *
 * Syncing and disconnecting are not plan-gated and are not hidden when a
 * plan lapses. A business that downgrades and then cannot pull its own
 * catalogue across, or cannot disconnect a shop it no longer uses, has
 * been locked in by its own cancellation.
 */
export function StorefrontPanel({
  workspaceId,
  provider,
  account,
  canManage,
  included,
}: {
  workspaceId: string;
  provider: StorefrontProvider;
  account: Storefront | null;
  canManage: boolean;
  included: boolean;
}) {
  const [installState, install] = useActionState<FormState, FormData>(
    beginInstall,
    null,
  );
  const [syncState, sync] = useActionState<FormState, FormData>(
    syncStorefront,
    null,
  );
  const [removeState, remove] = useActionState<FormState, FormData>(
    disconnectStorefront,
    null,
  );
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    // The provider's own approval page. Nothing is connected until the
    // shop owner approves it there and the provider calls back.
    if (installState?.checkoutUrl) window.location.assign(installState.checkoutUrl);
  }, [installState]);

  return (
    <Card data-provider={provider}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <h2>{STOREFRONT_LABEL[provider]}</h2>
          <Badge variant={account ? "default" : "outline"}>
            {account ? account.status : "Not connected"}
          </Badge>
        </CardTitle>
        <CardDescription>
          Pulls the catalogue, the orders and the customers across, so the
          assistant can answer about them.
        </CardDescription>
      </CardHeader>

      <CardContent className="grid gap-4">
        {account ? (
          <>
            <dl className="grid gap-1 text-sm">
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Shop</dt>
                <dd className="font-mono">{account.shop_domain}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Last synced</dt>
                <dd>
                  {account.last_synced_at
                    ? new Date(account.last_synced_at).toLocaleString(undefined, {
                        dateStyle: "medium",
                        timeStyle: "short",
                      })
                    : // Null until the first full read finishes.
                      "Not yet"}
                </dd>
              </div>
            </dl>

            <Refusal state={syncState ?? removeState} />

            {syncState?.sync ? (
              <p className="text-muted-foreground text-sm" role="status">
                {/*
                  `skipped` is the interesting number: records the shop sent
                  that were already as new here, which is what a retry looks
                  like from the inside.
                */}
                {syncState.sync.products} products, {syncState.sync.orders}{" "}
                orders, {syncState.sync.contacts} contacts.{" "}
                {syncState.sync.skipped} were already up to date.
              </p>
            ) : null}

            {canManage ? (
              <div className="flex flex-wrap items-center gap-2">
                <form action={sync}>
                  <input type="hidden" name="workspace_id" value={workspaceId} />
                  <input type="hidden" name="provider" value={provider} />
                  <Pending>Sync now</Pending>
                </form>

                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setConfirming(!confirming)}
                >
                  {confirming ? "Cancel" : "Disconnect"}
                </Button>
              </div>
            ) : null}

            {confirming && canManage ? (
              <form action={remove} className="grid gap-2 border-t pt-3">
                <input type="hidden" name="workspace_id" value={workspaceId} />
                <input type="hidden" name="provider" value={provider} />
                <input type="hidden" name="shop_domain" value={account.shop_domain} />

                {/*
                  What stops, and what does not. The API keeps everything
                  already synced on purpose: a business disconnecting a shop
                  has not asked to lose its own catalogue.
                */}
                <p className="text-muted-foreground text-sm">
                  New orders and product changes stop coming across. Everything
                  already here — products, orders, contacts — stays, and the
                  assistant goes on answering about it.
                </p>

                <Label htmlFor={`sf-confirm-${provider}`} className="text-xs">
                  Type <span className="font-mono">{account.shop_domain}</span> to
                  confirm
                </Label>
                <Input
                  id={`sf-confirm-${provider}`}
                  name="confirm"
                  autoComplete="off"
                  className="h-8 font-mono"
                  required
                />
                <Pending destructive>Disconnect this shop</Pending>
              </form>
            ) : null}
          </>
        ) : canManage ? (
          <form action={install} className="grid gap-3">
            <input type="hidden" name="workspace_id" value={workspaceId} />
            <input type="hidden" name="provider" value={provider} />

            <Refusal state={installState} />

            {!included ? (
              <p
                className="text-muted-foreground rounded-md border px-3 py-2 text-sm"
                data-testid="not-in-plan"
              >
                Your plan does not include storefronts.{" "}
                <Link href="/billing" className="underline underline-offset-4">
                  See what each plan includes
                </Link>
                .
              </p>
            ) : null}

            <div className="grid gap-2">
              <Label htmlFor={`shop-${provider}`}>Shop address</Label>
              <Input
                id={`shop-${provider}`}
                name="shop_domain"
                placeholder={
                  provider === "shopify" ? "acme.myshopify.com" : "shop.acme.com"
                }
                maxLength={255}
                className="font-mono"
                required
              />
              <FieldError>{installState?.fields?.shop_domain}</FieldError>
              <p className="text-muted-foreground text-xs">
                You will be sent to {STOREFRONT_LABEL[provider]} to approve it.
                Nothing is connected until you do.
              </p>
            </div>

            <SubmitButton className="w-fit">Connect</SubmitButton>
          </form>
        ) : (
          <p className="text-muted-foreground text-sm">
            Only an owner or an admin can connect a shop.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
