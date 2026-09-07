import { expect, test } from "@playwright/test";

import {
  addMemberViaApi,
  createWorkspaceViaApi,
  registerViaApi,
  signInThrough,
  someone,
} from "./support";

function slug() {
  return `w7-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
}

async function anOwnerWithAWorkspace() {
  const person = someone("Ada Okonkwo");
  const token = await registerViaApi(person);
  const workspace = await createWorkspaceViaApi(token, slug());

  return { person, token, workspace };
}

test("the price list renders for somebody with no account", async ({ page }) => {
  // Signed out entirely: no cookies, no session. Asking somebody to
  // register to find out what it costs is the wrong way round, which is
  // why the API serves /plans unauthenticated.
  await page.goto("/pricing");

  await expect(page.getByTestId("plan-list")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Starter" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Growth" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Business" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Sign in" })).toBeVisible();
});

test("a free plan says Free, and a paid one shows its real price", async ({
  page,
}) => {
  await page.goto("/pricing");

  const starter = page.locator('[data-tier="starter"]');
  const growth = page.locator('[data-tier="growth"]');

  await expect(starter).toContainText("Free");
  // 49 is the API's price as a string. Nothing on the way here parsed it.
  await expect(growth).toContainText("49");
});

test("unlimited is spelled out, never left blank", async ({ page }) => {
  await page.goto("/pricing");

  const business = page.locator('[data-tier="business"]');

  // Business has no ceiling on team members. A blank cell there would read
  // as a value the page failed to load.
  await expect(business).toContainText("Unlimited");
});

test("a new workspace is on the free plan and says so", async ({ page }) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await page.goto("/billing");

  await expect(page.getByRole("heading", { level: 2, name: "Starter" })).toBeVisible();
  await expect(page.getByText("Nothing has been paid for yet")).toBeVisible();
  // Never paid is not the same as payment failed.
  await expect(page.getByTestId("payment-warning")).toHaveCount(0);
});

test("usage meters show the ceiling the plan actually allows", async ({ page }) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await page.goto("/billing");

  const meters = page.getByTestId("usage-meters");

  await expect(meters).toBeVisible();
  // Starter allows two team members, and the workspace has its owner. The
  // number filling the meter is the number that refuses the third
  // invitation -- both come from the same measurement.
  await expect(meters.locator('[data-metric="team_members"]')).toContainText(
    "1 of 2",
  );
});

test("the free plan offers no checkout, because cancelling is the way back", async ({
  page,
}) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await page.goto("/billing");

  const starter = page.locator('[data-tier="starter"]');

  // The API refuses a checkout for a plan with nothing to pay, so a button
  // here would have exactly one outcome: a 502.
  await expect(starter.getByRole("button")).toHaveCount(0);
  await expect(starter).toContainText("Current");

  // A paid one does offer it.
  await expect(
    page.locator('[data-tier="growth"]').getByRole("button"),
  ).toBeVisible();
});

test("a provider that is not configured is reported as ours, not theirs", async ({
  page,
}) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await page.goto("/billing");

  await page.locator('[data-tier="growth"]').getByRole("button").click();

  // No Stripe key in a test deployment, so this is the provider-down path
  // -- which production meets too. It must not read as something the
  // customer did wrong, and it must not be the upgrade prompt either:
  // paying more would not help.
  const alert = page.getByRole("main").getByRole("alert");

  await expect(alert).toBeVisible();
  await expect(alert).toContainText("payment provider could not be reached");
  await expect(page.getByTestId("upgrade-prompt")).toHaveCount(0);
});

test("a member who cannot change the plan is told, and still sees it", async ({
  page,
}) => {
  const { token, workspace } = await anOwnerWithAWorkspace();
  const agent = someone("Agent Person");

  await addMemberViaApi(token, workspace.id, agent, "agent");
  await signInThrough(page, agent);
  await page.goto("/billing");

  // Any member may read this. Being told "your plan does not include this"
  // by a screen that will not say what the plan is would be a dead end.
  await expect(page.getByTestId("usage-meters")).toBeVisible();
  await expect(page.getByTestId("plan-list")).toBeVisible();
  await expect(
    page.getByText("Only an owner or an admin can change the plan"),
  ).toBeVisible();
  await expect(
    page.locator('[data-tier="growth"]').getByRole("button"),
  ).toHaveCount(0);
});

test("a plan limit reached renders the upgrade prompt, not a red box", async ({
  page,
}) => {
  const { person, token, workspace } = await anOwnerWithAWorkspace();

  // Starter allows two team members. The owner is one; one invitation
  // fills it, and the second is refused with a 402.
  await addMemberViaApi(token, workspace.id, someone("Second Person"), "agent");
  await signInThrough(page, person);
  await page.goto(`/workspaces/${workspace.id}/team`);

  await page.getByLabel("Email").fill(someone("Third Person").email);
  await page.getByRole("button", { name: "Create invitation" }).click();

  // The criterion: one prompt, everywhere, naming what is in the way and
  // linking to the plan. A 403 would send somebody to an administrator;
  // this sends them somewhere they can actually act.
  const prompt = page.getByTestId("upgrade-prompt");

  await expect(prompt).toBeVisible();
  await expect(prompt).toContainText("plan");
  await expect(
    prompt.getByRole("link", { name: "See what each plan includes" }),
  ).toHaveAttribute("href", "/billing");
});

test("the plan page is reachable from the account menu", async ({ page }) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await page.getByTestId("account-menu").click();
  await page.getByRole("menuitem", { name: "Plan and billing" }).click();

  await expect(
    page.getByRole("heading", { name: "Plan and billing" }),
  ).toBeVisible();
});
