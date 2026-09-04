import { expect, test } from "@playwright/test";

import {
  addMemberViaApi,
  createWorkspaceViaApi,
  registerThrough,
  registerViaApi,
  signInThrough,
  someone,
} from "./support";

/** A slug the API will take: lowercase words joined by single hyphens. */
function slug() {
  return `w2-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
}

test("a person with no workspace is asked to make one", async ({ page }) => {
  await registerThrough(page, someone());

  await expect(page.getByRole("heading", { name: "Create a workspace" })).toBeVisible();
  await expect(page.getByTestId("workspace-switcher")).toHaveText("Create a workspace");
});

test("creating a workspace switches to it", async ({ page }) => {
  await registerThrough(page, someone());
  const name = slug();

  await page.goto("/workspaces");
  await page.getByLabel("Name").fill(name);
  await page.getByRole("button", { name: "Create workspace" }).click();

  // The switcher is the proof it became current: creating one and being
  // left on the old one is a step everybody would have to take.
  await expect(page.getByTestId("workspace-switcher")).toContainText(name);
  await expect(page.getByRole("heading", { name })).toBeVisible();
});

test("the address is suggested from the name and stays editable", async ({ page }) => {
  await registerThrough(page, someone());

  await page.goto("/workspaces");
  await page.getByLabel("Name").fill("Ada & Co. Fashion");

  const address = page.getByLabel("Address");

  await expect(address).toHaveValue("ada-co-fashion");

  // Editable, because the API's rule has more than one reasonable answer
  // and the person naming their own business should pick.
  await address.fill("ada-fashion");
  await page.getByLabel("Name").fill("Ada & Co. Fashion Ltd");
  await expect(address).toHaveValue("ada-fashion");
});

test("an owner can rename a workspace, and the header follows", async ({ page }) => {
  const person = someone();
  const token = await registerViaApi(person);
  const workspace = await createWorkspaceViaApi(token, slug());

  await signInThrough(page, person);
  await page.goto(`/workspaces/${workspace.id}/settings`);

  await page.getByLabel("Name").fill("Renamed Business");
  await page.getByRole("button", { name: "Save" }).click();

  await expect(page.getByRole("status")).toHaveText("Saved.");
  // The switcher reads the same workspace, so a stale header here would
  // mean the layout was not revalidated.
  await expect(page.getByTestId("workspace-switcher")).toContainText(
    "Renamed Business",
  );
});

test("a viewer sees the settings disabled, not absent", async ({ page }) => {
  const owner = someone("Owner Person");
  const viewer = someone("Viewer Person");

  const ownerToken = await registerViaApi(owner);
  const workspace = await createWorkspaceViaApi(ownerToken, slug());

  await addMemberViaApi(ownerToken, workspace.id, viewer, "viewer");
  await signInThrough(page, viewer);
  await page.goto(`/workspaces/${workspace.id}/settings`);

  // Present and readable: somebody who cannot change these still needs to
  // see what they are, and to know who to ask.
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  await expect(page.getByLabel("Name")).toBeDisabled();
  await expect(page.getByText("Only an owner or an admin can change these")).toBeVisible();
  await expect(page.getByRole("button", { name: "Save" })).toHaveCount(0);

  // Closing is owner-only, so that section is not theirs at all.
  await expect(page.getByRole("heading", { name: "Close this workspace" })).toHaveCount(0);
});

test("closing a workspace needs its own slug typed", async ({ page }) => {
  const person = someone();
  const token = await registerViaApi(person);
  const workspace = await createWorkspaceViaApi(token, slug());

  await signInThrough(page, person);
  await page.goto(`/workspaces/${workspace.id}/settings`);

  const confirm = page.getByLabel(/Type .* to confirm/);

  // A word that is the same every time is one people learn to type without
  // reading, so the wrong one is refused before anything is called.
  await confirm.fill("close");
  await page.getByRole("button", { name: "Close this workspace" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText(workspace.slug);

  await confirm.fill(workspace.slug);
  await page.getByRole("button", { name: "Close this workspace" }).click();

  await expect(page).toHaveURL(/\/workspaces$/);
  // Gone from the tenant surface entirely, which is the API's doing.
  await expect(page.getByText(workspace.slug)).toHaveCount(0);
});

test("a workspace that is not yours is not found", async ({ page }) => {
  const stranger = someone("Stranger");
  const strangerToken = await registerViaApi(stranger);
  const theirs = await createWorkspaceViaApi(strangerToken, slug());

  await registerThrough(page, someone());
  await page.goto(`/workspaces/${theirs.id}/settings`);

  // The same answer as a workspace that does not exist. The API refuses to
  // distinguish them so an id cannot be used to discover who has an
  // account, and this screen must not be more helpful than that.
  await expect(page.getByText(/could not be found|not found/i).first()).toBeVisible();
});
