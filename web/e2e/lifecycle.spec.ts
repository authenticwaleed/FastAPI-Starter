import { expect, test } from "@playwright/test";

import {
  approveViaApi,
  closeWorkspaceViaApi,
  createWorkspaceViaApi,
  promoteToStaffViaCli,
  readViaApi,
  registerViaApi,
  signInToConsoleThrough,
  someone,
} from "./support";
import type { Approval, AuditEntry, Page as Paged } from "@/lib/types";

/**
 * What W12 is judged on: the first console phase that changes anything.
 *
 * Three criteria -- erasure cannot be triggered without typing the slug,
 * an action needing approval leaves a visible pending request, and
 * revoking your own staff access is refused with an explanation -- and
 * the whole two-person erasure, end to end, because the three criteria
 * are the parts of it that can go wrong quietly.
 */

function slug() {
  return `w12-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
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

test("suspending says why, and the business can read it", async ({ page }) => {
  const { person: staff, token: staffToken } = await aStaffMember();
  const { workspace } = await aBusiness();

  await signInToConsoleThrough(page, staff);
  await page.goto(`/console/workspaces/${workspace.id}/lifecycle`);

  await page
    .getByLabel("Why this account is being frozen")
    .fill("The invoice of 3 March is sixty days overdue after three reminders");
  await page.getByRole("button", { name: "Suspend this account" }).click();

  // The state moved, and the screen now offers the other direction rather
  // than leaving a dead control on it.
  await expect(page.locator('[data-status="suspended"]')).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Lift the suspension" }),
  ).toBeVisible();

  // And the reason reached the customer's own log, named as staff. Read
  // through the console's copy because reading an audit log is a paid
  // feature and this workspace is on the free plan.
  const log = await readViaApi<Paged<AuditEntry>>(
    `/admin/workspaces/${workspace.id}/audit?page_size=50`,
    staffToken,
  );
  const entry = log.items.find((row) => row.event === "workspace.suspended");

  expect(JSON.stringify(entry?.metadata)).toContain("sixty days overdue");

  await page.getByRole("button", { name: "Lift the suspension" }).click();
  await expect(page.locator('[data-status="active"]')).toBeVisible();
});

test("a move the state does not permit says which state, and re-renders", async ({
  page,
}) => {
  const { person: staff } = await aStaffMember();
  const { token: ownerToken, workspace } = await aBusiness();

  await signInToConsoleThrough(page, staff);
  await page.goto(`/console/workspaces/${workspace.id}/lifecycle`);
  await page.getByLabel("Type").fill(workspace.slug);

  // Somebody else moves it first -- the customer closing their own account
  // from the app, which is exactly the race this refusal exists for. The
  // screen in front of us was right when it rendered and is not any more.
  await closeWorkspaceViaApi(ownerToken, workspace.id);

  await page.getByRole("button", { name: "Close this account" }).click();

  // The 409 says which state refused it, not just that something did.
  await expect(page.getByRole("alert").first()).toHaveAttribute(
    "data-code",
    "workspace_lifecycle",
  );
  await expect(page.getByTestId("refusal-detail")).toContainText("already closed");

  // And the controls that come back are the ones that now apply, rather
  // than a close button somebody presses a third time.
  await expect(
    page.getByRole("button", { name: "Restore this account" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Close this account" }),
  ).toHaveCount(0);
});

test("erasure cannot be triggered without typing the slug", async ({ page }) => {
  const { person: staff, token: staffToken } = await aStaffMember();
  const other = await aStaffMember("admin");
  const { workspace } = await aBusiness();

  await signInToConsoleThrough(page, staff);
  await page.goto(`/console/workspaces/${workspace.id}/erase`);

  // Nothing to press before a colleague has agreed.
  await expect(page.getByTestId("confirm-slug")).toHaveCount(0);

  await page
    .getByLabel("What you are asking them to agree to")
    .fill("They asked to be forgotten on 2 September and confirmed it by reply");
  await page.getByRole("button", { name: "Ask a colleague" }).click();

  // The criterion: a visible pending request, not a silent one.
  await expect(page.getByTestId("approval-pending")).toContainText("asked to be forgotten");

  const approvals = await readViaApi<Paged<Approval>>("/admin/approvals", staffToken);
  const raised = approvals.items.find(
    (approval) => approval.subject === workspace.id,
  );

  await approveViaApi(other.token, raised!.id);
  await page.reload();

  // Now the form exists, and the wrong name is refused on the field.
  await page.getByTestId("confirm-slug").fill("not-the-right-slug");
  await page.getByRole("button", { name: "Erase this workspace for ever" }).click();

  await expect(page.getByRole("alert").first()).toHaveAttribute(
    "data-code",
    "confirmation_mismatch",
  );

  // The workspace is still there, which is the half of this that matters.
  await readViaApi(`/admin/workspaces/${workspace.id}`, staffToken);
});

test("two people, the right name, and the business is gone", async ({ page }) => {
  const { person: staff, token: staffToken } = await aStaffMember();
  const other = await aStaffMember("admin");
  const { workspace } = await aBusiness();

  await signInToConsoleThrough(page, staff);
  await page.goto(`/console/workspaces/${workspace.id}/erase`);

  await page
    .getByLabel("What you are asking them to agree to")
    .fill("Closed in error by the owner and re-created; this one is empty");
  await page.getByRole("button", { name: "Ask a colleague" }).click();
  await expect(page.getByTestId("approval-pending")).toBeVisible();

  const approvals = await readViaApi<Paged<Approval>>("/admin/approvals", staffToken);
  const raised = approvals.items.find(
    (approval) => approval.subject === workspace.id,
  );

  await approveViaApi(other.token, raised!.id);
  await page.reload();

  await page.getByTestId("confirm-slug").fill(workspace.slug);
  await page.getByRole("button", { name: "Erase this workspace for ever" }).click();

  // There is nothing to come back to, so it leaves for the list.
  await expect(page).toHaveURL(/\/console\/workspaces\?erased=1/);

  // And the entry naming it survives the workspace it is about, which is
  // the reason the platform log does not cascade.
  const log = await readViaApi<Paged<{ action: string; subject: unknown }>>(
    "/admin/audit?action=workspace.erased&page_size=50",
    staffToken,
  );

  expect(JSON.stringify(log.items)).toContain(workspace.slug);
});

test("revoking your own staff access is refused, with the reason", async ({
  page,
}) => {
  const { person: staff } = await aStaffMember();

  // A second owner, so the API itself would allow the revoke. What stops
  // it is that this client will not hand somebody the button that signs
  // them out of the console.
  await aStaffMember("owner");

  await signInToConsoleThrough(page, staff);
  await page.goto("/console/staff");

  const mine = page.locator('[data-testid="staff-row"]', {
    has: page.getByText(staff.email),
  });

  await expect(mine.getByTestId("your-own-row")).toContainText(
    "would sign you out of the console",
  );
  await expect(mine.getByRole("button", { name: "Take access away" })).toHaveCount(0);
  await expect(mine.getByRole("button", { name: "Change" })).toHaveCount(0);
});

test("an owner promotion says it needs a colleague before it is tried", async ({
  page,
}) => {
  const { person: staff, token: staffToken } = await aStaffMember();
  const newcomer = someone("Newly Registered");

  await registerViaApi(newcomer);

  const found = await readViaApi<{ items: { id: number; email: string }[] }>(
    `/admin/users?q=${encodeURIComponent(newcomer.email)}`,
    staffToken,
  );
  const id = found.items[0].id;

  await signInToConsoleThrough(page, staff);
  await page.goto(`/console/staff?grant=${id}`);

  // Support and admin are ordinary promotions one person decides.
  await expect(page.getByRole("button", { name: "Give access" })).toBeVisible();

  await page.getByTestId("grant-access").getByLabel("Rank").selectOption("owner");

  // Owner is not, and the screen says so rather than letting somebody
  // press a button that answers 403.
  await expect(page.getByTestId("owner-needs-approval")).toBeVisible();
  await expect(page.getByRole("button", { name: "Give access" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Ask a colleague" })).toBeVisible();
});

test("an account can be turned off and back on from its own page", async ({
  page,
}) => {
  const { person: staff, token: staffToken } = await aStaffMember();
  const person = someone("Ordinary Person");

  await registerViaApi(person);

  const found = await readViaApi<{ items: { id: number }[] }>(
    `/admin/users?q=${encodeURIComponent(person.email)}`,
    staffToken,
  );
  const id = found.items[0].id;

  await signInToConsoleThrough(page, staff);
  await page.goto(`/console/users/${id}`);

  await page.getByRole("button", { name: "Turn this account off" }).click();
  await expect(page.getByTestId("deactivated")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Turn this account back on" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Turn this account back on" }).click();
  await expect(page.getByTestId("deactivated")).toHaveCount(0);
});
