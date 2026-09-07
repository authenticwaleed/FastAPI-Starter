import { expect, test, type Page } from "@playwright/test";

import {
  addMemberViaApi,
  createWorkspaceViaApi,
  registerViaApi,
  signInThrough,
  somePhone,
  someone,
} from "./support";

function slug() {
  return `w8-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
}

/**
 * A phone number id nothing else holds.
 *
 * It is unique across every workspace at the API, not per workspace: a
 * webhook arrives carrying one and nothing else, so it is what turns a
 * delivery into a workspace. A fixed value here passes once and collides
 * on every run afterwards.
 */
function somePhoneNumberId(): string {
  return String(Date.now()).slice(-9) + String(Math.floor(Math.random() * 900) + 100);
}

async function anOwnerWithAWorkspace() {
  const person = someone("Ada Okonkwo");
  const token = await registerViaApi(person);
  const workspace = await createWorkspaceViaApi(token, slug());

  return { person, token, workspace };
}

/**
 * Every test here runs on the free plan, which does not include
 * automations or storefronts. That is the interesting condition rather
 * than a limitation: the rule this phase turns on is that only *creating*
 * is gated, and a plan that excludes them is the only way to see whether
 * the screens got that right.
 */
async function tryToSwitchOn(page: Page, kind: string) {
  await page.goto("/automations");
  await page
    .locator(`li[data-kind="${kind}"]`)
    .getByRole("button", { name: "Switch it on" })
    .click();
}

test("a plan without automations says so before anything is pressed", async ({
  page,
}) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await page.goto("/automations");

  // Told up front rather than after a 402. The refusal still renders if
  // somebody presses anyway, but nobody should have to press to find out.
  await expect(page.getByTestId("not-in-plan")).toBeVisible();
  await expect(
    page.getByTestId("not-in-plan").getByRole("link"),
  ).toHaveAttribute("href", "/billing");
});

test("pressing anyway renders the upgrade prompt, not a red box", async ({
  page,
}) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await tryToSwitchOn(page, "order_confirmation");

  // The same prompt as everywhere else in the client: the plan is what is
  // in the way, and the plan is something this person can change.
  const prompt = page.getByTestId("upgrade-prompt");

  await expect(prompt).toBeVisible();
  await expect(prompt).toContainText("plan");
});

test("all three automations are offered, and described", async ({ page }) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await page.goto("/automations");

  // A fixed list rather than a builder, which is the API's shape.
  for (const kind of [
    "order_confirmation",
    "human_handoff",
    "unanswered_lead_followup",
  ]) {
    await expect(page.locator(`li[data-kind="${kind}"]`)).toBeVisible();
  }

  await expect(page.getByText("When an order arrives")).toBeVisible();
  await expect(page.getByText(/nudges a customer nobody ever replied to/i)).toBeVisible();
});

test("the integrations page shows both, unconnected, without erroring", async ({
  page,
}) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await page.goto("/integrations");

  // Not having connected anything is the ordinary state of a new
  // workspace, so a 404 from the API must not surface as a failure.
  await expect(page.getByTestId("whatsapp-panel")).toContainText("Not connected");
  await expect(page.locator('[data-provider="shopify"]')).toBeVisible();
  await expect(page.locator('[data-provider="woocommerce"]')).toBeVisible();
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
});

test("connecting WhatsApp asks for a token and never shows one back", async ({
  page,
}) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await page.goto("/integrations");

  const panel = page.getByTestId("whatsapp-panel");

  await expect(panel.getByLabel("Access token")).toHaveAttribute(
    "type",
    "password",
  );

  await panel.getByLabel("Phone number", { exact: true }).fill(somePhone());
  await panel.getByLabel("Phone number ID").fill(somePhoneNumberId());
  await panel.getByLabel("Access token").fill("a-token-that-is-not-real");
  await panel.getByRole("button", { name: "Connect" }).click();

  await expect(panel).toContainText("Connected");
  // The API returns no token field of any kind, so there is nothing to
  // pre-fill a box with -- and the screen must not invent one.
  await expect(panel.getByLabel("Access token")).toHaveCount(0);
  await expect(panel).toContainText("never shown again");
});

test("disconnecting WhatsApp says what stops, and asks for the number", async ({
  page,
}) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await page.goto("/integrations");

  const panel = page.getByTestId("whatsapp-panel");

  const number = somePhone();

  await panel.getByLabel("Phone number", { exact: true }).fill(number);
  await panel.getByLabel("Phone number ID").fill(somePhoneNumberId());
  await panel.getByLabel("Access token").fill("a-token-that-is-not-real");
  await panel.getByRole("button", { name: "Connect" }).click();
  await expect(panel).toContainText("Connected");

  await panel.getByRole("button", { name: "Disconnect", exact: true }).click();

  // The criterion: say what stops working, and what does not.
  await expect(panel).toContainText("New messages stop arriving");
  await expect(panel).toContainText("Everything already in the inbox stays");

  // The wrong value is refused before anything is called.
  await panel.getByLabel(/Type .* to confirm/).fill("+920000000000");
  await panel.getByRole("button", { name: "Disconnect this number" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "Type the number to confirm",
  );

  await panel.getByLabel(/Type .* to confirm/).fill(number);
  await panel.getByRole("button", { name: "Disconnect this number" }).click();
  await expect(panel).toContainText("Not connected");
});

test("a storefront install on a plan without it is refused, and says why", async ({
  page,
}) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await page.goto("/integrations");

  const shopify = page.locator('[data-provider="shopify"]');

  await expect(shopify.getByTestId("not-in-plan")).toBeVisible();

  await shopify.getByLabel("Shop address").fill("acme.myshopify.com");
  await shopify.getByRole("button", { name: "Connect" }).click();

  await expect(page.getByTestId("upgrade-prompt")).toBeVisible();
});

test("a failed install lands somewhere that explains itself", async ({ page }) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);

  // The provider sends the browser back whatever happened. A page that
  // only handled success would leave somebody staring at a screen that
  // had not changed.
  await page.goto("/integrations?failed=shopify");

  const outcome = page.getByTestId("install-outcome");

  await expect(outcome).toBeVisible();
  await expect(outcome).toContainText("was not connected");
  await expect(outcome).toContainText("starting again is safe");
});

test("a successful install lands on something that says so", async ({ page }) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await page.goto("/integrations?connected=acme.myshopify.com");

  await expect(page.getByTestId("install-outcome")).toContainText(
    "acme.myshopify.com is connected",
  );
});

test("a viewer reads both and is offered nothing", async ({ page }) => {
  const { token, workspace } = await anOwnerWithAWorkspace();
  const viewer = someone("Viewer Person");

  await addMemberViaApi(token, workspace.id, viewer, "viewer");
  await signInThrough(page, viewer);

  await page.goto("/integrations");
  await expect(page.getByTestId("whatsapp-panel")).toContainText(
    "Only an owner or an admin",
  );
  await expect(page.getByLabel("Access token")).toHaveCount(0);

  await page.goto("/automations");
  await expect(
    page.getByRole("heading", { name: "Switch on an automation" }),
  ).toHaveCount(0);
});
