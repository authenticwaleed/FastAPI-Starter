import { expect, test } from "@playwright/test";

import {
  connectWhatsAppViaApi,
  createContactViaApi,
  createWorkspaceViaApi,
  deliverBillingEventViaApi,
  openConversationViaApi,
  promoteToStaffViaCli,
  registerViaApi,
  runTheWorker,
  sendMessageViaApi,
  signInToConsoleThrough,
  somePhone,
  someone,
} from "./support";

/**
 * What W13 is judged on: the last phase, and everything the console still
 * could not do.
 *
 * Four criteria -- the `past_due` list one click from the home, a grant
 * with no expiry visibly flagged, a replay that says what it did and
 * changes nothing, and a failed job showing why before offering a retry.
 *
 * The approvals screen is here too, because it closes the loop W12 opens
 * and neither half is worth much without the other.
 */

function slug() {
  return `w13-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
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

test("the retried subscriptions are one click from the console home", async ({
  page,
}) => {
  const { person: staff } = await aStaffMember();

  await signInToConsoleThrough(page, staff);

  // The criterion, read literally: from the front door, in one click.
  await page.getByRole("link", { name: "Being retried" }).click();

  await expect(page).toHaveURL(/\/console\/billing\?status=past_due/);
  await expect(page.getByTestId("list-past_due")).toBeVisible();

  // And it is a list of its own rather than a value in a dropdown, so it
  // can be linked to, bookmarked and sent to somebody.
  await expect(page.getByRole("heading", { name: "Subscriptions" })).toBeVisible();
});

test("a granted plan with no expiry is flagged rather than refused", async ({
  page,
}) => {
  const { person: staff } = await aStaffMember();
  const { workspace } = await aBusiness();

  await signInToConsoleThrough(page, staff);
  await page.goto(`/console/workspaces/${workspace.id}/subscription`);

  await page
    .getByLabel("Why")
    .fill("Six-month pilot agreed with them on 3 March, invoiced offline");
  await page.getByRole("button", { name: "Grant this plan" }).click();

  // The criterion. Leaving the date out is allowed -- a comp somebody
  // negotiated has no natural end -- and the answer is a warning rather
  // than a refusal, because a plan nothing will ever take away is worth
  // being told about.
  const granted = page.getByTestId("granted-override");

  await expect(granted).toBeVisible();
  await expect(granted).toHaveAttribute("data-forever", "");
  await expect(page.getByTestId("forever-flag")).toBeVisible();
  await expect(granted).toContainText("Nothing will ever take this away");

  // And it is what actually applies afterwards, not just what was typed.
  await page.reload();
  await expect(page.getByTestId("entitled-plan")).toContainText("growth");

  await page.getByRole("button", { name: "Remove any granted plan" }).click();
  await expect(page.getByTestId("override-removed")).toBeVisible();
  await expect(page.getByTestId("entitled-plan")).toContainText("starter");
});

test("replaying says what it did, and pressing it again changes nothing", async ({
  page,
}) => {
  const { person: staff } = await aStaffMember();
  const eventId = await deliverBillingEventViaApi();

  await signInToConsoleThrough(page, staff);
  await page.goto("/console/billing/events?event_type=invoice.payment_failed");

  const row = page.locator('[data-event-type="invoice.payment_failed"]').first();

  await expect(row).toContainText(eventId);

  await row.getByRole("button", { name: "Apply again" }).click();

  // The criterion. This delivery names a subscription this platform does
  // not hold, so there was nothing to do -- an ordinary answer, and one
  // that must not be coloured as a failure.
  await expect(row.getByTestId("replay-result")).toContainText("Nothing to apply");
  await expect(row.getByRole("alert")).toHaveCount(0);

  // Safe to press twice: what gets applied is the provider's own
  // snapshot, so it lands on the same values either way.
  await row.getByRole("button", { name: "Apply again" }).click();
  await expect(row.getByTestId("replay-result")).toContainText("Nothing to apply");
});

test("a failed job says why before it offers a retry", async ({ page }) => {
  const { person: staff } = await aStaffMember();
  const { token, workspace } = await aBusiness();

  // A number connected with a token the provider refuses, which is the
  // only honest way to get a job with an error on it: the send fails, the
  // API enqueues the retry in the same transaction, and one pass of the
  // worker attempts it and writes down what came back.
  await connectWhatsAppViaApi(token, workspace.id);

  const contact = await createContactViaApi(
    token,
    workspace.id,
    somePhone(),
    "Farah Customer",
  );
  const conversation = await openConversationViaApi(token, workspace.id, contact.id);

  await sendMessageViaApi(token, workspace.id, conversation.id, "never arrives").catch(
    () => {
      // The 502 is the point. Nothing to assert on it here.
    },
  );

  await runTheWorker();

  await signInToConsoleThrough(page, staff);
  await page.goto(
    `/console/jobs?kind=deliver_message&workspace_id=${workspace.id}`,
  );

  // The reason is on the row, so the queue answers the ticket without a
  // second read. What the reason *says* depends on why the provider
  // refused -- a rejected token, or a deployment that cannot decrypt one
  // -- and asserting the sentence would be asserting the API's prose.
  // That there is one, on the row, is the claim.
  await expect(page.getByTestId("job-error").first()).not.toBeEmpty();

  await page.getByTestId("job-list").getByRole("link").first().click();

  // The criterion: why it failed comes before what can be done about it.
  // Pressing retry without reading the error is how a message that will
  // fail for the same reason gets sent four more times.
  const error = page.getByTestId("job-error");
  const retry = page.getByRole("button", { name: "Put it back in the queue" });

  await expect(error).toBeVisible();
  await expect(retry).toBeVisible();

  const errorBox = await error.boundingBox();
  const retryBox = await retry.boundingBox();

  expect(errorBox!.y).toBeLessThan(retryBox!.y);
});

test("a job can be put back, and cancelling is its own answer", async ({ page }) => {
  const { person: staff } = await aStaffMember();
  const { token, workspace } = await aBusiness();
  const contact = await createContactViaApi(token, workspace.id, somePhone(), "C");
  const conversation = await openConversationViaApi(token, workspace.id, contact.id);

  await sendMessageViaApi(token, workspace.id, conversation.id, "queued");

  await signInToConsoleThrough(page, staff);
  await page.goto(
    `/console/jobs?kind=deliver_message&status=pending&workspace_id=${workspace.id}`,
  );
  await page.getByTestId("job-list").getByRole("link").first().click();

  await page.getByRole("button", { name: "Cancel it" }).click();

  // Its own status rather than `failed`, because the two answer different
  // questions afterwards: a failure is something to investigate, and this
  // is something somebody already decided about.
  await expect(page.locator('[data-status="cancelled"]')).toBeVisible();
});

test("health is a page, and says what configured means", async ({ page }) => {
  const { person: staff } = await aStaffMember();

  await signInToConsoleThrough(page, staff);
  await page.goto("/console/health");

  await expect(page.getByTestId("health-checks")).toContainText("Database");
  // The word is doing careful work, so the page explains it rather than
  // letting somebody read it as "the provider answered".
  await expect(page.getByText(/Configured means a key is present/)).toBeVisible();
  // And nothing on it refreshes: every read here is a row in the log.
  await expect(page.locator("meta[http-equiv='refresh']")).toHaveCount(0);
});

test("an approval raised in one place is agreed to by somebody else", async ({
  page,
}) => {
  const asker = await aStaffMember();
  const agreer = await aStaffMember("admin");
  const { workspace } = await aBusiness();

  await signInToConsoleThrough(page, asker.person);
  await page.goto(`/console/workspaces/${workspace.id}/erase`);
  await page
    .getByLabel("What you are asking them to agree to")
    .fill("Closed in error by the owner and re-created; this one is empty");
  await page.getByRole("button", { name: "Ask a colleague" }).click();
  await expect(page.getByTestId("approval-pending")).toBeVisible();

  // Their own request offers them nothing: agreeing to it yourself is a
  // form with extra steps, which is the whole control.
  await page.goto("/console/approvals");

  const request = page.locator('[data-action="erase_workspace"]').first();

  await expect(request.getByTestId("your-own-request")).toBeVisible();
  await expect(request.getByRole("button", { name: "Agree to this" })).toHaveCount(0);

  // The colleague, in their own console session, can.
  await page.getByRole("button", { name: "Sign out of the console" }).click();
  await signInToConsoleThrough(page, agreer.person);
  await page.goto("/console/approvals");

  const theirs = page.locator('[data-action="erase_workspace"]').first();

  await theirs.getByRole("button", { name: "Agree to this" }).click();
  await expect(
    page.locator('[data-action="erase_workspace"]').first(),
  ).toHaveAttribute("data-state", "agreed");
});

test("the alert feed counts accounts opened, and refuses nobody", async ({
  page,
}) => {
  const { person: staff } = await aStaffMember();
  const businesses = [await aBusiness(), await aBusiness(), await aBusiness()];

  await signInToConsoleThrough(page, staff);

  // Reading a customer's account is what the feed is built from -- the
  // same rows that answer "who looked at this workspace". Three of them,
  // so this reader is above everybody who opened one: the API returns the
  // busiest twenty, and a shared database is full of people with one.
  for (const business of businesses) {
    await page.goto(`/console/workspaces/${business.workspace.id}`);
  }

  await page.goto("/console/alerts?hours=1");

  const mine = page
    .getByTestId("busiest-readers")
    .getByRole("listitem")
    .filter({ hasText: staff.email });

  await expect(mine).toContainText("3 accounts");

  // Distinct businesses rather than requests: refreshing one account's
  // page forty times is working, and opening forty is a question. So a
  // fourth read of a workspace already counted moves nothing.
  await page.goto(`/console/workspaces/${businesses[0].workspace.id}`);
  await page.goto("/console/alerts?hours=1");
  await expect(
    page
      .getByTestId("busiest-readers")
      .getByRole("listitem")
      .filter({ hasText: staff.email }),
  ).toContainText("3 accounts");

  // Nothing here stops anybody doing anything, so there is nothing to press.
  await expect(page.getByTestId("busiest-readers").getByRole("button")).toHaveCount(
    0,
  );
});
