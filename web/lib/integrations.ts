/**
 * Reading automations and the two integrations.
 *
 * The queries only. What each automation is and what settings it takes is
 * `lib/automations.ts`, which is pure so the forms can import it.
 */

import { api, apiOrNull } from "@/lib/api";
import { STOREFRONTS } from "@/lib/labels";
import type {
  Automation,
  AutomationRun,
  Page,
  Storefront,
  StorefrontProvider,
  WhatsAppAccount,
} from "@/lib/types";

/** Unpaginated at the API: there are three of them. */
export function listAutomations(workspaceId: string) {
  return api<Automation[]>(`/workspaces/${workspaceId}/automations`);
}

export function readAutomation(workspaceId: string, automationId: string) {
  return api<Automation>(
    `/workspaces/${workspaceId}/automations/${automationId}`,
  );
}

export function listRuns(workspaceId: string, automationId: string, page = 1) {
  return api<Page<AutomationRun>>(
    `/workspaces/${workspaceId}/automations/${automationId}/runs` +
      `?page=${page}&page_size=20`,
  );
}

/**
 * The connected number, or nothing.
 *
 * `null` rather than a thrown 404: not having connected one is the
 * ordinary state of a new workspace, and a screen that treated it as a
 * failure would greet everybody with an error on their first visit.
 */
export function readWhatsApp(workspaceId: string) {
  return apiOrNull<WhatsAppAccount>(
    `/workspaces/${workspaceId}/integrations/whatsapp`,
  );
}

export function readStorefront(workspaceId: string, provider: StorefrontProvider) {
  return apiOrNull<Storefront>(
    `/workspaces/${workspaceId}/integrations/${provider}`,
  );
}

/** Every storefront this workspace has, in one pass. */
export async function readStorefronts(workspaceId: string) {
  const found = await Promise.all(
    STOREFRONTS.map(async (provider) => ({
      provider,
      account: await readStorefront(workspaceId, provider),
    })),
  );

  return found;
}
