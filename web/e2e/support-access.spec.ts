import { expect, test } from "@playwright/test";

import {
  createContactViaApi,
  createWorkspaceViaApi,
  endSupportAccessViaApi,
  openConversationViaApi,
  promoteToStaffViaCli,
  readViaApi,
  registerViaApi,
  sendMessageViaApi,
  signInToConsoleThrough,
  somePhone,
  someone,
} from "./support";
import type { AdminAuditEntry, AuditEntry, Page as Paged } from "@/lib/types";

/**
 * What W11 is judged on, and the phase the plan asks to be slowed down for.
 *
 * Three criteria: a read without a grant is refused and offers the request
 * flow, a grant that ends while a thread is open stops further reads, and
 * asking twice says one is already live.
 *
 * Two more are pinned here because they are the promises the phase makes
 * to somebody who is not in the room: the customer can see in their own
 * log that staff were here, and opening the inbox does not record threads
 * nobody opened.
 */

function slug() {
  return `w11-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
}

async function aStaffMember(role: "support" | "admin" | "owner" = "owner") {
  const person = someone("Staff Person");
  const token = await registerViaApi(person);

  await promoteToStaffViaCli(person.email, role);

  return { person, token };
}

/** A business with one customer who has said something. */
async function aBusinessWithAThread() {
  const person = someone("Ada Okonkwo");
  const token = await registerViaApi(person);
  const workspace = await createWorkspaceViaApi(token, slug());
  const contact = await createContactViaApi(
    token,
    workspace.id,
    somePhone(),
    "Farah Customer",
  );
  const conversation = await openConversationViaApi(token, workspace.id, contact.id);

  await sendMessageViaApi(
    token,
    workspace.id,
    conversation.id,
    "The parcel never turned up",
  );

  return { person, token, workspace, conversation };
}

async function askForAccess(
  page: import("@playwright/test").Page,
  workspaceId: string,
  reason = "To investigate the delivery failure they reported on Tuesday",
) {
  await page.goto(`/console/workspaces/${workspaceId}/support-access`);
  await page.getByLabel("Why you need to look").fill(reason);
  await page.getByRole("button", { name: "Ask for access" }).click();
  await expect(page.getByTestId("support-window")).toBeVisible();
}

test("a thread without a grant is refused, and the form is right there", async ({
  page,
}) => {
  const { person: staff } = await aStaffMember();
  const { workspace, conversation } = await aBusinessWithAThread();

  await signInToConsoleThrough(page, staff);
  await page.goto(
    `/console/workspaces/${workspace.id}/conversations/${conversation.id}`,
  );

  // The criterion. Not a wall and not a fault: it means ask for access,
  // so asking is a thing you do here rather than a page you go and find.
  await expect(page.getByTestId("needs-access")).toBeVisible();
  await expect(page.getByTestId("request-access")).toBeVisible();
  await expect(page.getByTestId("message-thread")).toHaveCount(0);
});

test("asking, then reading, then the window closing mid-thread", async ({
  page,
}) => {
  const { person: staff, token: staffToken } = await aStaffMember();
  const { workspace, conversation } = await aBusinessWithAThread();

  await signInToConsoleThrough(page, staff);
  await askForAccess(page, workspace.id);

  await page.goto(
    `/console/workspaces/${workspace.id}/conversations/${conversation.id}`,
  );

  await expect(page.getByTestId("message-thread")).toContainText(
    "The parcel never turned up",
  );
  // Always on screen while customer data is.
  await expect(page.getByTestId("support-window")).toHaveAttribute(
    "data-state",
    "open",
  );
  // And never in the first person. A staff member is not on this team, so
  // nothing here is addressed to them as if the threads were theirs.
  await expect(page.getByTestId("message-thread")).toContainText("The team");
  await expect(page.getByTestId("message-thread")).not.toContainText("You");

  await page.goto(`/console/workspaces/${workspace.id}/conversations`);
  await expect(page.getByTestId("console-inbox")).toContainText("The team");
  await expect(page.getByTestId("console-inbox")).not.toContainText("you send");
  await expect(page.getByTestId("console-inbox")).not.toContainText("You have this");

  await page.goto(
    `/console/workspaces/${workspace.id}/conversations/${conversation.id}`,
  );

  // The grant ends underneath them. Expiry cannot be waited out -- an hour
  // is the shortest window the API opens -- and revoking is the same
  // refusal, deliberately: unknown, expired and revoked are one answer.
  await endSupportAccessViaApi(staffToken, workspace.id);

  await page.reload();

  await expect(page.getByTestId("needs-access")).toBeVisible();
  await expect(page.getByTestId("message-thread")).toHaveCount(0);
});

test("asking a second time says one is already live", async ({ page }) => {
  const { person: staff } = await aStaffMember();
  const { workspace } = await aBusinessWithAThread();

  await signInToConsoleThrough(page, staff);
  await askForAccess(page, workspace.id);

  // The screen shows the window rather than the form once one is live, so
  // the second ask arrives the way it would in a second tab: from a screen
  // that did not know.
  await page.goto(`/console/workspaces/${workspace.id}/conversations`);
  await expect(page.getByTestId("console-inbox")).toBeVisible();

  await page.goto(`/console/workspaces/${workspace.id}/support-access`);
  await expect(page.getByTestId("request-access")).toHaveCount(0);
  await expect(page.getByTestId("grant-list")).toContainText("live");
});

test("the customer's own log says staff were here, and who", async ({
  page,
}) => {
  const { person: staff, token: staffToken } = await aStaffMember();
  const { workspace } = await aBusinessWithAThread();

  await signInToConsoleThrough(page, staff);
  await askForAccess(page, workspace.id, "To check why their orders stopped syncing");

  // No silent power: the entry is in the *business's* own log, with the
  // reason typed into the console and the address of who typed it.
  //
  // Read here through the console's copy of that log rather than as the
  // customer, because reading an audit log is a paid feature and this
  // workspace is on the free plan -- the API's own known caveat, which
  // says the entry is held either way. The console's route is not gated,
  // deliberately: whether support can answer a ticket about a log is not
  // a decision that business's plan gets to make.
  const log = await readViaApi<Paged<AuditEntry>>(
    `/admin/workspaces/${workspace.id}/audit?page_size=50`,
    staffToken,
  );
  const granted = log.items.find(
    (entry) => entry.event === "support.access_granted",
  );

  expect(granted).toBeDefined();
  expect(JSON.stringify(granted?.metadata)).toContain("orders stopped syncing");
  expect(JSON.stringify(granted?.metadata)).toContain(staff.email);

  // And the screen that renders that log names them. The API leaves the
  // actor empty so a staff member never appears among the customer's own
  // colleagues -- which a screen could easily render as "Not a person",
  // telling a business nobody was in their account.
  await page.goto(`/console/workspaces/${workspace.id}/audit`);

  const entry = page.locator('[data-event="support.access_granted"]');

  await expect(entry).toContainText("Baton support");
  await expect(entry).toContainText(staff.email);
  await expect(entry).not.toContainText("Not a person");
});

test("opening the inbox does not record threads nobody opened", async ({
  page,
}) => {
  const { person: staff, token: staffToken } = await aStaffMember();
  const { workspace, conversation } = await aBusinessWithAThread();

  await signInToConsoleThrough(page, staff);
  await askForAccess(page, workspace.id);

  await page.goto(`/console/workspaces/${workspace.id}/conversations`);
  await expect(page.getByTestId("console-inbox")).toBeVisible();

  // The worst row this client could write: a support engineer recorded as
  // having read a customer's thread because a link scrolled into view.
  // Every link in the console has prefetching off; this is what checks it.
  const after = await readViaApi<Paged<AdminAuditEntry>>(
    `/admin/audit?workspace_id=${workspace.id}&page_size=200`,
    staffToken,
  );
  const actions = after.items.map((entry) => entry.action);

  expect(actions).toContain("workspace.conversations_read");
  expect(actions).not.toContain("workspace.messages_read");

  // And it is recorded when somebody actually opens one.
  await page.goto(
    `/console/workspaces/${workspace.id}/conversations/${conversation.id}`,
  );
  await expect(page.getByTestId("message-thread")).toBeVisible();

  const opened = await readViaApi<Paged<AdminAuditEntry>>(
    `/admin/audit?workspace_id=${workspace.id}&page_size=200`,
    staffToken,
  );

  expect(opened.items.map((entry) => entry.action)).toContain(
    "workspace.messages_read",
  );
});

test("there is nothing on a thread that could write to it", async ({ page }) => {
  const { person: staff } = await aStaffMember();
  const { workspace, conversation } = await aBusinessWithAThread();

  await signInToConsoleThrough(page, staff);
  await askForAccess(page, workspace.id);
  await page.goto(
    `/console/workspaces/${workspace.id}/conversations/${conversation.id}`,
  );

  await expect(page.getByTestId("message-thread")).toBeVisible();
  // Read-only, and visibly so. The API would refuse a write from a staff
  // actor anyway -- the access carries no membership, so its role is
  // viewer -- but a box to type in would be a promise this surface does
  // not keep.
  await expect(page.getByRole("textbox")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /send/i })).toHaveCount(0);
});

test("support rank may ask for access and may not review who had it", async ({
  page,
}) => {
  const { person: staff } = await aStaffMember("support");
  const { workspace } = await aBusinessWithAThread();

  await signInToConsoleThrough(page, staff);
  await page.goto(`/console/workspaces/${workspace.id}/support-access`);

  // The API's split, and the reason for it: the rank that answers tickets
  // is the one that needs access, and the rank that oversees them is the
  // one that reviews whether they should have had it.
  await expect(page.getByTestId("request-access")).toBeVisible();
  await expect(page.getByTestId("history-refused")).toContainText(
    "staff role does not include this",
  );
});
