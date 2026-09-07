import { expect, test } from "@playwright/test";

import {
  addMemberViaApi,
  createWorkspaceViaApi,
  registerViaApi,
  signInThrough,
  someone,
} from "./support";

function slug() {
  return `w9-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
}

async function anOwnerWithAWorkspace() {
  const person = someone("Ada Okonkwo");
  const token = await registerViaApi(person);
  const workspace = await createWorkspaceViaApi(token, slug());

  return { person, token, workspace };
}

test("a brand-new workspace shows zeroes rather than an error", async ({ page }) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await page.goto("/analytics");

  // Nothing has happened yet, which is a number rather than a failure.
  await expect(page.getByRole("heading", { name: "Analytics" })).toBeVisible();
  await expect(page.locator('[data-stat="Conversations"]')).toContainText("0");
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
});

test("nothing answered yet is a dash, never an instant reply", async ({ page }) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await page.goto("/analytics");

  const tile = page.locator('[data-stat="First reply"]');

  // "0s" here would report a response time no business achieved. The API
  // sends null precisely so a screen can tell the two apart.
  await expect(tile).toContainText("—");
  await expect(tile).toContainText("Nothing answered yet");
  await expect(tile).not.toContainText("0s");
});

test("a backwards range lands on the picker, not on a broken page", async ({
  page,
}) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await page.goto("/analytics?start=2026-03-01&end=2026-01-01");

  // 422, and it is the person's to fix — so the range picker is still
  // there to fix it with.
  await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
  await expect(page.getByLabel("From")).toBeVisible();
  await expect(page.getByLabel("To")).toBeVisible();
});

test("the range lives in the address, so a view can be shared", async ({ page }) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await page.goto("/analytics");

  await page.getByLabel("From").fill("2026-01-01");
  await page.getByLabel("To").fill("2026-01-31");
  await page.getByRole("button", { name: "Apply" }).click();

  await expect(page).toHaveURL(/start=2026-01-01.*end=2026-01-31/);
  await expect(page.getByRole("link", { name: "Clear" })).toBeVisible();
});

test("the chart names itself and labels both ends of the range", async ({
  page,
}) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await page.goto("/analytics");

  // A single series, so identity comes from the title rather than a
  // legend box — and the accessible name carries the reading for anybody
  // who cannot see the line at all.
  const chart = page.getByRole("img", { name: /conversations by day/i });

  await expect(chart).toBeVisible();
  // Every axis label names a value the scale actually reaches.
  await expect(chart.locator("text").first()).toBeVisible();
});

test("a plan without the audit log gets a prompt, not a 403 page", async ({
  page,
}) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await page.goto("/audit");

  // The criterion. A 402 says the plan is in the way and the plan is
  // something they can change; a 403 page would be a wall with nothing
  // behind it.
  const prompt = page.getByTestId("upgrade-prompt");

  await expect(prompt).toBeVisible();
  await expect(prompt.getByRole("link")).toHaveAttribute("href", "/billing");
  await expect(page.getByRole("heading", { name: "Audit log" })).toBeVisible();
  // And the reassurance that matters: it is being kept meanwhile.
  await expect(page.getByText(/being kept either way/)).toBeVisible();
});

test("a plan without API access still lets a key be revoked", async ({ page }) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await page.goto("/api-keys");

  // Creating is gated and says so. Revoking is not, which is the point:
  // a downgrade must not leave live credentials nobody can turn off.
  await expect(page.getByTestId("not-in-plan")).toBeVisible();
  await expect(page.getByTestId("not-in-plan")).toContainText(
    "go on working until you revoke them",
  );
  await expect(
    page.getByRole("heading", { name: "Keys", exact: true }),
  ).toBeVisible();
});

test("creating a key on a plan without it renders the upgrade prompt", async ({
  page,
}) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await page.goto("/api-keys");

  await page.getByLabel("What is it for").fill("Staging server");
  await page.getByRole("button", { name: "Create key" }).click();

  await expect(page.getByTestId("upgrade-prompt")).toBeVisible();
  // And no key was revealed, obviously — but worth pinning, because a
  // reveal panel appearing on a failure would be alarming.
  await expect(page.getByTestId("key-reveal")).toHaveCount(0);
});

test("an agent may read the numbers but not the keys", async ({ page }) => {
  const { token, workspace } = await anOwnerWithAWorkspace();
  const agent = someone("Agent Person");

  await addMemberViaApi(token, workspace.id, agent, "agent");
  await signInThrough(page, agent);

  // Knowing how the inbox is going is not administration.
  await page.goto("/analytics");
  await expect(page.getByRole("heading", { name: "Analytics" })).toBeVisible();
  await expect(page.locator('[data-stat="Conversations"]')).toBeVisible();

  // Making credentials is. The point is that this is a sentence rather
  // than a crash -- the list is admin-only at the API, and an unhandled
  // 403 would render "this page could not load".
  await page.goto("/api-keys");
  await expect(page.getByTestId("not-permitted")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Create a key" })).toHaveCount(0);
});
