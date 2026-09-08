import { expect, test } from "@playwright/test";

import {
  closeWorkspaceViaApi,
  createWorkspaceViaApi,
  deleteAccountViaApi,
  promoteToStaffViaCli,
  readViaApi,
  registerViaApi,
  signInThrough,
  signInToConsoleThrough,
  someone,
} from "./support";
import type { AdminAuditEntry, Page as Paged } from "@/lib/types";

/**
 * What W10 is judged on.
 *
 * Three criteria, and the first is the one that shapes every screen in the
 * console: nothing here issues a request the person did not ask for. It is
 * checked the only way it can honestly be checked -- against the platform's
 * own audit log, which is the record of every request the console made.
 */

function slug() {
  return `w10-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
}

async function aStaffMember(role: "support" | "admin" | "owner" = "owner") {
  const person = someone("Staff Person");
  const token = await registerViaApi(person);

  await promoteToStaffViaCli(person.email, role);

  return { person, token };
}

async function aBusiness() {
  const person = someone("Ada Okonkwo");
  const token = await registerViaApi(person);
  const workspace = await createWorkspaceViaApi(token, slug());

  return { person, token, workspace };
}

/** What the platform recorded about one workspace, newest first. */
async function actionsAbout(token: string, workspaceId: string) {
  const log = await readViaApi<Paged<AdminAuditEntry>>(
    `/admin/audit?workspace_id=${workspaceId}&page_size=200`,
    token,
  );

  return log.items.map((entry) => entry.action);
}

test("opening a workspace reads the workspace, and nothing else", async ({
  page,
}) => {
  const { person: staff, token: staffToken } = await aStaffMember();
  const { workspace } = await aBusiness();

  await signInToConsoleThrough(page, staff);
  await page.goto(`/console/workspaces/${workspace.id}`);
  await expect(page.getByRole("heading", { name: workspace.name })).toBeVisible();

  // The criterion. Members, subscription, usage, connections and the
  // business's own log are five further endpoints, and a detail page that
  // filled in some tabs with them would record a support engineer as
  // having read a customer's whole account when all they did was check
  // whether it was suspended.
  const opened = await actionsAbout(staffToken, workspace.id);

  expect(opened).toContain("workspace.read");
  expect(opened).not.toContain("workspace.members_read");
  expect(opened).not.toContain("workspace.subscription_read");
  expect(opened).not.toContain("workspace.usage_read");
  expect(opened).not.toContain("workspace.integrations_read");
  expect(opened).not.toContain("workspace.audit_read");

  // And the other half of it: each one is paid for by somebody opening it.
  await page.getByRole("link", { name: "Members" }).click();
  await expect(page.getByRole("heading", { name: "Members" })).toBeVisible();

  expect(await actionsAbout(staffToken, workspace.id)).toContain(
    "workspace.members_read",
  );
});

test("a workspace with nobody in it renders", async ({ page }) => {
  const { person: staff } = await aStaffMember();
  const { token: ownerToken, workspace } = await aBusiness();

  // A business that wound up and an owner who then left. Closing first is
  // not optional: the API refuses to delete the last owner of a live
  // workspace, which is what makes this sequence the real one.
  await closeWorkspaceViaApi(ownerToken, workspace.id);
  await deleteAccountViaApi(ownerToken);

  await signInToConsoleThrough(page, staff);
  await page.goto(`/console/workspaces/${workspace.id}/members`);

  await expect(page.getByTestId("no-members")).toBeVisible();
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
});

test("an account in no workspace renders, sessions and all", async ({ page }) => {
  const { person: staff } = await aStaffMember();

  // Registered and never went further, which is a common state rather than
  // an error -- and the reason the API answers it with two empty lists.
  const newcomer = someone("Newly Registered");

  await registerViaApi(newcomer);

  await signInToConsoleThrough(page, staff);
  await page.goto("/console/users");
  await page.getByLabel("Address or name").fill(newcomer.email);
  await page.getByRole("button", { name: "Search" }).click();
  await page.getByRole("link", { name: newcomer.name }).click();

  await expect(page.getByTestId("no-memberships")).toBeVisible();
  // Registering signs somebody in, so this one has a session. The empty
  // case is pinned above; what matters here is that neither list crashes.
  await expect(page.getByTestId("session-list")).toBeVisible();
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
});

test("a closed workspace is here, with the date its records go", async ({
  page,
}) => {
  const { person: staff } = await aStaffMember();
  const { token: ownerToken, workspace } = await aBusiness();

  await closeWorkspaceViaApi(ownerToken, workspace.id);

  await signInToConsoleThrough(page, staff);
  await page.goto(`/console/workspaces/${workspace.id}`);

  // The customer's own API pretends a closed workspace is gone. This one
  // does not, and the date is the answer to "it was closed last week".
  await expect(page.getByTestId("erase-after")).toContainText(
    "records are due to be destroyed",
  );
  await expect(page.locator('[data-status="cancelled"]').first()).toBeVisible();
});

test("the console is not reachable from any customer-facing screen", async ({
  page,
}) => {
  const { person } = await aBusiness();

  await signInThrough(page, person);

  // No door. Not in the shell, not in the account menu, not anywhere.
  await expect(page.locator('a[href^="/console"]')).toHaveCount(0);
  await page.goto("/account");
  await expect(page.locator('a[href^="/console"]')).toHaveCount(0);

  // And no door for a script either. The relay carries the tenant session,
  // and the platform surface is not its to reach -- so an XSS in the app
  // cannot read a customer's account from the other side.
  const refused = await page.request.get("/api/admin/me");

  expect(refused.status()).toBe(403);
  expect((await refused.json()).code).toBe("not_relayed");
});

test("the console has its own door, even for somebody already signed in", async ({
  page,
}) => {
  const { person: staff } = await aStaffMember();

  await signInThrough(page, staff);
  await page.goto("/console");

  // Signed in to Baton, and that says nothing about the console: §3.5 is
  // the reason the two hold separate sessions at all.
  await expect(page).toHaveURL(/\/console\/sign-in/);
  await expect(page.getByRole("heading", { name: "Platform console" })).toBeVisible();
});

test("signing out of the console leaves the app signed in", async ({ page }) => {
  const { person: staff } = await aStaffMember();

  await signInThrough(page, staff);
  await signInToConsoleThrough(page, staff);

  await page.getByRole("button", { name: "Sign out of the console" }).click();
  await expect(page).toHaveURL(/\/console\/sign-in/);

  // The criterion §3.5 exists for: a console session ending must not throw
  // somebody out of their own inbox.
  await page.goto("/");
  await expect(page.getByTestId("account-menu")).toBeVisible();
});

test("an account that is not staff is told so, with nothing to click", async ({
  page,
}) => {
  const { person } = await aBusiness();

  await signInToConsoleThrough(page, person);

  const refusal = page.getByTestId("console-refusal");

  await expect(refusal).toHaveAttribute("data-code", "not_staff");
  // Terminal. No retry, no upgrade prompt, no form that helps -- offering
  // one would only teach somebody to press it before reading it.
  await expect(refusal.getByRole("link")).toHaveCount(0);
  await expect(refusal.getByRole("button")).toHaveCount(0);
});

test("support rank meets a sentence at the platform log, not a crash", async ({
  page,
}) => {
  const { person: staff } = await aStaffMember("support");

  await signInToConsoleThrough(page, staff);
  await page.goto("/console/audit");

  // Admin rank at the API. The link is shown to everybody because knowing
  // the rank would cost a call on every screen -- so this refusal has to
  // read as an answer rather than as a broken page.
  await expect(page.getByTestId("console-refusal")).toHaveAttribute(
    "data-code",
    "insufficient_staff_role",
  );
  await expect(page.getByRole("heading", { name: "Platform log" })).toBeVisible();
});
