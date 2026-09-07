import { expect, test, type Page } from "@playwright/test";

import {
  addMemberViaApi,
  createWorkspaceViaApi,
  registerThrough,
  registerViaApi,
  signInThrough,
  signOutThrough,
  someone,
} from "./support";

function slug() {
  return `w4-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
}

/**
 * Create an invitation through the screens and read the link back.
 *
 * Through the screens on purpose: the token is returned exactly once and
 * showing it is the only way it reaches anybody, so the copyable link is
 * part of the behaviour rather than a convenience.
 */
async function inviteThrough(
  page: Page,
  workspaceId: string,
  email: string,
  role: string,
): Promise<string> {
  await page.goto(`/workspaces/${workspaceId}/team`);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Role").selectOption(role);
  await page.getByRole("button", { name: "Create invitation" }).click();

  const link = page.getByTestId("invitation-link");

  await expect(link).toBeVisible();

  return (await link.innerText()).trim();
}

test("an invitation link is shown once, because nothing emails it", async ({
  page,
}) => {
  const owner = someone("Owner Person");
  const token = await registerViaApi(owner);
  const workspace = await createWorkspaceViaApi(token, slug());
  const invitee = someone("Invited Person");

  await signInThrough(page, owner);

  const link = await inviteThrough(page, workspace.id, invitee.email, "agent");

  expect(link).toContain("/invitations/");
  await expect(page.getByText("It is shown once")).toBeVisible();

  // The invitation is listed as pending, and reloading does not show the
  // token again -- there is nothing to show it from.
  await page.reload();
  await expect(page.getByTestId("invitation-list")).toContainText(invitee.email);
  await expect(page.getByTestId("invitation-link")).toHaveCount(0);
});

test("inviting somebody twice says so and keeps what was typed", async ({ page }) => {
  const owner = someone("Owner Person");
  const token = await registerViaApi(owner);
  const workspace = await createWorkspaceViaApi(token, slug());
  const invitee = someone("Invited Person");

  await signInThrough(page, owner);
  await inviteThrough(page, workspace.id, invitee.email, "agent");

  await page.getByLabel("Email").fill(invitee.email);
  await page.getByRole("button", { name: "Create invitation" }).click();

  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "already been invited",
  );
  // The next thing somebody does is change one character, so the form must
  // not have been emptied under them.
  await expect(page.getByLabel("Email")).toHaveValue(invitee.email);
});

test("the whole invitation flow works from a signed-out browser", async ({ page }) => {
  const owner = someone("Owner Person");
  const ownerToken = await registerViaApi(owner);
  const workspace = await createWorkspaceViaApi(ownerToken, slug());
  const invitee = someone("Invited Person");

  await signInThrough(page, owner);

  const link = await inviteThrough(page, workspace.id, invitee.email, "agent");
  const path = new URL(link).pathname;

  await signOutThrough(page);

  // Signed out, and the preview still renders: whoever is reading it may
  // not have an account yet, which is the point of having been invited.
  await page.goto(path);
  await expect(
    page.getByRole("heading", { name: `Join ${workspace.name}` }),
  ).toBeVisible();
  await expect(page.getByText(invitee.email)).toBeVisible();
  await expect(page.getByRole("button", { name: "Accept and join" })).toHaveCount(0);

  // Register as the invited address, then come back to the link.
  await registerThrough(page, invitee);
  await page.goto(path);
  await page.getByRole("button", { name: "Accept and join" }).click();

  // Straight into the workspace just joined, rather than onto somebody
  // else's.
  await expect(page.getByTestId("workspace-switcher")).toContainText(workspace.name);
});

test("an invitation link opens for somebody who is already signed in", async ({
  page,
}) => {
  const owner = someone("Owner Person");
  const ownerToken = await registerViaApi(owner);
  const workspace = await createWorkspaceViaApi(ownerToken, slug());
  const invitee = someone("Invited Person");

  await registerViaApi(invitee);
  await signInThrough(page, owner);

  const link = await inviteThrough(page, workspace.id, invitee.email, "viewer");
  const path = new URL(link).pathname;

  await signOutThrough(page);
  await signInThrough(page, invitee);

  // The common case, and the one a blanket "public pages redirect signed-in
  // people home" rule would have broken: the link arrives while you are
  // already signed in.
  await page.goto(path);
  await expect(
    page.getByRole("heading", { name: `Join ${workspace.name}` }),
  ).toBeVisible();
});

test("a link that admits somebody else says whose it is", async ({ page }) => {
  const owner = someone("Owner Person");
  const ownerToken = await registerViaApi(owner);
  const workspace = await createWorkspaceViaApi(ownerToken, slug());
  const invitee = someone("Invited Person");
  const stranger = someone("Somebody Else");

  await registerViaApi(stranger);
  await signInThrough(page, owner);

  const link = await inviteThrough(page, workspace.id, invitee.email, "agent");
  const path = new URL(link).pathname;

  await signOutThrough(page);
  await signInThrough(page, stranger);
  await page.goto(path);
  await page.getByRole("button", { name: "Accept and join" }).click();

  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "sent to a different address",
  );
});

test("an unknown link explains itself rather than looking broken", async ({ page }) => {
  await page.goto("/invitations/not-a-real-token");

  await expect(
    page.getByRole("heading", { name: "This link does not work" }),
  ).toBeVisible();
});

test("an admin cannot change an owner's role, and the row says why", async ({
  page,
}) => {
  const owner = someone("Owner Person");
  const admin = someone("Admin Person");

  const ownerToken = await registerViaApi(owner);
  const workspace = await createWorkspaceViaApi(ownerToken, slug());

  await addMemberViaApi(ownerToken, workspace.id, admin, "admin");
  await signInThrough(page, admin);
  await page.goto(`/workspaces/${workspace.id}/team`);

  const ownerRow = page.getByTestId("member-list").locator('li[data-role="owner"]');

  await expect(ownerRow).toContainText("Only an owner can change this");
  await expect(ownerRow.locator("select")).toHaveCount(0);

  // And an admin cannot hand out their own rank either, which is the move
  // that would otherwise turn admin into owner in two steps.
  const options = await page.getByLabel("Role", { exact: true }).locator("option").allInnerTexts();

  expect(options).toContain("agent");
  expect(options).not.toContain("admin");
  expect(options).not.toContain("owner");
});

test("an owner can change a colleague's role", async ({ page }) => {
  const owner = someone("Owner Person");
  const agent = someone("Agent Person");

  const ownerToken = await registerViaApi(owner);
  const workspace = await createWorkspaceViaApi(ownerToken, slug());

  await addMemberViaApi(ownerToken, workspace.id, agent, "agent");
  await signInThrough(page, owner);
  await page.goto(`/workspaces/${workspace.id}/team`);

  const row = page.getByTestId("member-list").locator('li[data-role="agent"]');

  await row.locator("select").selectOption("admin");
  await row.getByRole("button", { name: "Save" }).click();

  await expect(
    page.getByTestId("member-list").locator('li[data-role="admin"]'),
  ).toContainText("Agent Person");
});

test("the only owner cannot leave, and is told what to do first", async ({ page }) => {
  const owner = someone("Owner Person");
  const token = await registerViaApi(owner);
  const workspace = await createWorkspaceViaApi(token, slug());

  await signInThrough(page, owner);
  await page.goto(`/workspaces/${workspace.id}/team`);

  await page.getByLabel(/Type LEAVE to confirm/).fill("LEAVE");
  await page.getByRole("button", { name: "Leave this workspace" }).click();

  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "at least one owner",
  );
  await expect(page.getByText(/Give somebody else the owner role/)).toBeVisible();
});

test("a member can leave, and stops seeing the workspace", async ({ page }) => {
  const owner = someone("Owner Person");
  const agent = someone("Agent Person");

  const ownerToken = await registerViaApi(owner);
  const workspace = await createWorkspaceViaApi(ownerToken, slug());

  await addMemberViaApi(ownerToken, workspace.id, agent, "agent");
  await signInThrough(page, agent);
  await page.goto(`/workspaces/${workspace.id}/team`);

  await page.getByLabel(/Type LEAVE to confirm/).fill("LEAVE");
  await page.getByRole("button", { name: "Leave this workspace" }).click();

  await expect(page).toHaveURL(/\/workspaces$/);
  await expect(page.getByText(workspace.slug)).toHaveCount(0);
});

test("a viewer sees the team but not the invitations", async ({ page }) => {
  const owner = someone("Owner Person");
  const viewer = someone("Viewer Person");

  const ownerToken = await registerViaApi(owner);
  const workspace = await createWorkspaceViaApi(ownerToken, slug());

  await addMemberViaApi(ownerToken, workspace.id, viewer, "viewer");
  await signInThrough(page, viewer);
  await page.goto(`/workspaces/${workspace.id}/team`);

  // Any member may see who they work with. The invitation list is a list of
  // addresses of people being recruited, which is not everybody's business
  // -- the API draws the line in the same place.
  await expect(page.getByTestId("member-list")).toContainText("Owner Person");
  await expect(page.getByRole("heading", { name: "Invitations" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Invite somebody" })).toHaveCount(0);
  // Leaving needs no rank.
  await expect(page.getByRole("button", { name: "Leave this workspace" })).toBeVisible();
});
