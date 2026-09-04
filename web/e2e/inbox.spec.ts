import { expect, test } from "@playwright/test";

import {
  addMemberViaApi,
  closeConversationViaApi,
  createContactViaApi,
  createWorkspaceViaApi,
  openConversationViaApi,
  registerViaApi,
  signInThrough,
  somePhone,
  someone,
} from "./support";

function slug() {
  return `w3-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
}

/** An owner with a workspace, a contact and a thread already open. */
async function aThread() {
  const person = someone("Ada Okonkwo");
  const token = await registerViaApi(person);
  const workspace = await createWorkspaceViaApi(token, slug());
  const contact = await createContactViaApi(
    token,
    workspace.id,
    somePhone(),
    "Rana Customer",
  );
  const conversation = await openConversationViaApi(token, workspace.id, contact.id);

  return { person, token, workspace, contact, conversation };
}

test("the inbox opens on what is still somebody's problem", async ({ page }) => {
  const { person } = await aThread();

  await signInThrough(page, person);
  await page.goto("/inbox");

  await expect(page.getByRole("heading", { name: "Inbox" })).toBeVisible();
  await expect(page.getByTestId("conversation-row")).toHaveCount(1);
  await expect(page.getByTestId("conversation-list")).toContainText("Rana Customer");

  // Closed is a filter somebody asks for, never a default.
  await expect(page.getByRole("link", { name: "Live" })).toHaveClass(/font-medium/);
});

test("a reply appears in the thread, and is queued rather than sent", async ({
  page,
}) => {
  const { person, conversation } = await aThread();

  await signInThrough(page, person);
  await page.goto(`/inbox/${conversation.id}`);

  await page.getByLabel("Your reply").fill("We have it in stock, yes.");
  await page.getByRole("button", { name: "Send", exact: true }).click();

  const thread = page.getByTestId("message-thread");

  await expect(thread).toContainText("We have it in stock, yes.");
  // Everything this API sends stays queued until the messaging phase
  // delivers it, so a screen implying "sent" would be telling an agent
  // their customer already has the reply.
  await expect(thread.getByText("Queued")).toBeVisible();
});

test("a closed conversation offers reopening and nothing else", async ({ page }) => {
  const { person, token, workspace, conversation } = await aThread();

  await closeConversationViaApi(token, workspace.id, conversation.id);
  await signInThrough(page, person);
  await page.goto(`/inbox/${conversation.id}`);

  await expect(page.getByRole("button", { name: "Reopen" })).toBeVisible();
  await expect(page.getByText("Reopen it to reply")).toBeVisible();

  // The API refuses a reply to a closed thread, so a composer here would
  // be a control whose only outcome is a refusal.
  await expect(page.getByLabel("Your reply")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Take over" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Close" })).toHaveCount(0);

  await page.getByRole("button", { name: "Reopen" }).click();
  await expect(page.getByLabel("Your reply")).toBeVisible();
});

test("a thread somebody else closed says so, and refreshes rather than erroring", async ({
  page,
}) => {
  const { person, token, workspace, conversation } = await aThread();

  await signInThrough(page, person);
  await page.goto(`/inbox/${conversation.id}`);
  await expect(page.getByLabel("Your reply")).toBeVisible();

  // A colleague closes it while this page is open. Two people working one
  // inbox will do this to each other, and it is not a fault.
  await closeConversationViaApi(token, workspace.id, conversation.id);

  await page.getByLabel("Your reply").fill("Are you still there?");
  await page.getByRole("button", { name: "Send", exact: true }).click();

  const notice = page.getByRole("status").filter({ hasText: "refreshed" });

  await expect(notice).toBeVisible();
  await expect(notice).toContainText("was not sent");
  // And the thread now shows the truth, rather than a composer that would
  // only be refused again.
  await expect(page.getByRole("button", { name: "Reopen" })).toBeVisible();
  // Told, not shouted at: this is somebody else moving first.
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
});

test("the assistant's answer never lands in the thread as a message", async ({
  page,
}) => {
  const { person, conversation } = await aThread();

  await signInThrough(page, person);
  await page.goto(`/inbox/${conversation.id}`);

  const before = await page.getByTestId("message-thread").count();

  await page.getByRole("button", { name: "Draft a reply" }).click();

  // Whatever it decides -- drafted, handed off, or the model unreachable --
  // the one thing that must not happen is text appearing in the thread as
  // though the customer had received it. In a test deployment with no
  // model configured this exercises the refusal path, which is the half
  // where a careless client would render a draft as a sent message.
  await expect(page.getByRole("heading", { name: "Assistant" })).toBeVisible();
  await expect(page.getByTestId("message-thread")).toHaveCount(before);
});

test("a viewer reads the thread and is told why they cannot reply", async ({
  page,
}) => {
  const viewer = someone("Viewer Person");
  const { token, workspace, conversation } = await aThread();

  await addMemberViaApi(token, workspace.id, viewer, "viewer");
  await signInThrough(page, viewer);
  await page.goto(`/inbox/${conversation.id}`);

  // Absent rather than disabled, unlike the workspace settings form: there
  // is nothing to read off a greyed-out box, and a permanently dead
  // composer is worse than none.
  await expect(page.getByLabel("Your reply")).toHaveCount(0);
  await expect(page.getByText("Replying needs the agent role")).toBeVisible();
  await expect(page.getByRole("button", { name: "Close" })).toHaveCount(0);
  await expect(page.getByTestId("message-thread")).toBeVisible();
});

test("taking over and handing back is one control in two states", async ({ page }) => {
  const { person, conversation } = await aThread();

  await signInThrough(page, person);
  await page.goto(`/inbox/${conversation.id}`);

  await page.getByRole("button", { name: "Take over" }).click();
  await expect(page.getByTestId("conversation-state")).toHaveText("You have this");

  await page.getByRole("button", { name: "Hand back to the assistant" }).click();
  // Back to drafting, not to answering: a thread somebody had to take over
  // is not one to put straight onto full automation.
  await expect(page.getByTestId("conversation-state")).toHaveText(
    "Assistant drafts, you send",
  );
});

test("a contact with no conversations is an empty state, not an error", async ({
  page,
}) => {
  const person = someone();
  const token = await registerViaApi(person);
  const workspace = await createWorkspaceViaApi(token, slug());
  const contact = await createContactViaApi(token, workspace.id, somePhone(), "Nobody Yet");

  await signInThrough(page, person);
  await page.goto(`/contacts/${contact.id}`);

  await expect(page.getByRole("heading", { name: "Nobody Yet" })).toBeVisible();
  await expect(page.getByText("Nothing yet with this contact.")).toBeVisible();
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
});

test("a contact can be given a thread, and only one at a time", async ({ page }) => {
  const person = someone();
  const token = await registerViaApi(person);
  const workspace = await createWorkspaceViaApi(token, slug());
  const contact = await createContactViaApi(token, workspace.id, somePhone(), "Rana");

  await signInThrough(page, person);
  await page.goto(`/contacts/${contact.id}`);

  await page.getByRole("button", { name: "Open a conversation" }).click();
  await expect(page).toHaveURL(/\/inbox\/[0-9a-f-]+$/);

  // A contact holds one open thread at a time. Pressing it again is
  // somebody else having got there first, not a fault.
  await page.goto(`/contacts/${contact.id}`);
  await page.getByRole("button", { name: "Open a conversation" }).click();
  await expect(page.getByRole("status")).toContainText("already has an open conversation");
});

test("adding a contact lands on its profile", async ({ page }) => {
  const person = someone();
  const token = await registerViaApi(person);

  await createWorkspaceViaApi(token, slug());
  await signInThrough(page, person);
  await page.goto("/contacts");

  await page.getByLabel("Phone number").fill(somePhone());
  await page.getByLabel("Name", { exact: true }).fill("Newly Added");
  await page.getByRole("button", { name: "Add contact" }).click();

  await expect(page).toHaveURL(/\/contacts\/[0-9a-f-]+$/);
  await expect(page.getByRole("heading", { name: "Newly Added" })).toBeVisible();
});
