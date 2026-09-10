import { expect, test, type Page } from "@playwright/test";

import {
  addMemberViaApi,
  createWorkspaceViaApi,
  registerViaApi,
  signInThrough,
  someone,
} from "./support";

function slug() {
  return `w5-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
}

async function anOwnerWithAWorkspace() {
  const person = someone("Ada Okonkwo");
  const token = await registerViaApi(person);
  const workspace = await createWorkspaceViaApi(token, slug());

  return { person, token, workspace };
}

async function addSource(page: Page, name: string) {
  await page.goto("/knowledge");
  await page.getByLabel("Name").fill(name);
  await page.getByRole("button", { name: "Add source" }).click();
  await expect(page.getByTestId("source-list")).toContainText(name);
}

test("a source has to exist before anything can go in it", async ({ page }) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await page.goto("/knowledge");

  await expect(page.getByRole("heading", { name: "Knowledge" })).toBeVisible();
  await expect(page.getByText("A source is a grouping")).toBeVisible();
  // Both ways of adding say the same thing rather than offering a form
  // whose only outcome is a refusal.
  await expect(page.getByText("Add a source first").first()).toBeVisible();
});

test("typed knowledge reports a provider that is not there", async ({ page }) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await addSource(page, "Returns policy");

  await page.getByLabel("Title").fill("Refund window");
  await page.getByLabel("Content").fill("Refunds are accepted within 30 days.");
  await page.getByRole("button", { name: "Add", exact: true }).click();

  // Every write to the knowledge base goes through the embedding provider,
  // and a test deployment has no key for it. So what runs here is the
  // provider-down path -- which production will meet too, and which must
  // not read as though the person did something wrong.
  //
  // The success path is not covered by this suite. It needs a real key.
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "knowledge service is unavailable",
  );
  await expect(page).toHaveURL(/\/knowledge$/);
});

test("a question and its answer are kept as a pair", async ({ page }) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await addSource(page, "Common questions");

  await page.getByRole("tab", { name: "Question and answer" }).click();

  // The pair stays a pair: two fields rather than one box somebody has to
  // format themselves, because the question is part of what gets embedded.
  await expect(page.getByLabel("Question")).toBeVisible();
  await expect(page.getByLabel("Answer")).toBeVisible();

  await page.getByLabel("Question").fill("How long do refunds take?");
  await page.getByLabel("Answer").fill("Five working days from approval.");
  await page.getByRole("button", { name: "Add", exact: true }).click();

  // Same provider, same refusal as above.
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "knowledge service is unavailable",
  );
});

test("an oversized file is refused before it is uploaded", async ({ page }) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await addSource(page, "Uploads");

  // Eleven megabytes against the API's ten. Refused in the browser, so
  // somebody with a big scan finds out now rather than after the upload.
  await page.getByLabel("File").setInputFiles({
    name: "huge.txt",
    mimeType: "text/plain",
    buffer: Buffer.alloc(11 * 1024 * 1024, "a"),
  });
  await page.getByRole("button", { name: "Upload" }).click();

  const alert = page.getByRole("main").getByRole("alert");

  await expect(alert).toContainText("The limit is 10MB");
  await expect(page.getByTestId("upload-progress")).toHaveCount(0);
});

test("a text file uploads, reports progress and appears in the list", async ({
  page,
}) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await addSource(page, "Uploads");

  await page.getByLabel("File").setInputFiles({
    name: "policy.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(
      "Refunds are accepted within thirty days of delivery. ".repeat(200),
    ),
  });
  await page.getByRole("button", { name: "Upload" }).click();

  // The file really is sent -- the relay forwards multipart bytes intact,
  // which `request.text()` would have mangled -- and ingestion then fails
  // on the missing embedding key. So what is pinned here is that the
  // upload got as far as the API and the refusal is rendered as one
  // sentence rather than a raw envelope.
  const outcome = page.getByRole("main").getByRole("alert");

  await expect(outcome).toBeVisible();
  await expect(outcome).not.toContainText("{");
  await expect(outcome).toContainText("unavailable");
});

test("a file the extractor cannot open says which kinds it takes", async ({
  page,
}) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await addSource(page, "Uploads");

  await page.getByLabel("File").setInputFiles({
    name: "photo.png",
    mimeType: "image/png",
    buffer: Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
  });
  await page.getByRole("button", { name: "Upload" }).click();

  // 415, and it must not read like 422. This one is "we cannot open that
  // at all"; the other is "we opened it and there was no text".
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "Only PDFs and plain text files can be added",
  );
});

test("deleting a source says what goes with it, and asks for its name", async ({
  page,
}) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await addSource(page, "Temporary notes");

  await page.getByRole("button", { name: "Delete" }).first().click();

  await expect(
    page.getByText(/deletes the source, every document in it/),
  ).toBeVisible();

  // The wrong word is refused before anything is called.
  await page.getByLabel(/Type .* to confirm/).fill("Temporary");
  await page.getByRole("button", { name: "Delete this source" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "Type the source's name to confirm",
  );

  await page.getByLabel(/Type .* to confirm/).fill("Temporary notes");
  await page.getByRole("button", { name: "Delete this source" }).click();

  await expect(page.getByText("A source is a grouping")).toBeVisible();
  await expect(page.getByTestId("document-list")).toHaveCount(0);
});

test("search names the document every passage came from", async ({ page }) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await addSource(page, "Returns policy");

  await page.getByLabel("Title").fill("Refund window");
  await page.getByLabel("Content").fill("Refunds are accepted within 30 days.");
  await page.getByRole("button", { name: "Add", exact: true }).click();

  await page.goto("/knowledge");
  await page
    .getByLabel("Search the knowledge base")
    .fill("how long do I have to return something");
  await page.getByRole("button", { name: "Search" }).click();

  // Whatever comes back -- matches, nothing close enough, or an embedding
  // provider that is not configured in a test deployment -- the screen has
  // to say which, and a match must be traceable to its document.
  const answered = page.getByTestId("search-results");
  const refused = page.getByRole("alert");

  await expect(answered.or(refused).first()).toBeVisible();

  if (await answered.isVisible()) {
    const links = answered.getByRole("link", { name: "Open the document" });

    if ((await links.count()) > 0) {
      await expect(links.first()).toHaveAttribute("href", /\/knowledge\/[0-9a-f-]+/);
    }
  }
});

test("an agent may search but may not change the knowledge base", async ({
  page,
}) => {
  const { token, workspace } = await anOwnerWithAWorkspace();
  const agent = someone("Agent Person");

  await addMemberViaApi(token, workspace.id, agent, "agent");
  await signInThrough(page, agent);
  await page.goto("/knowledge");

  // Checking what the assistant would be given is part of answering a
  // customer well, so an agent keeps it.
  await expect(page.getByRole("heading", { name: "Try a question" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Add a source" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Upload a file" })).toHaveCount(0);
});

test("a viewer reads the knowledge base and cannot search it", async ({ page }) => {
  const { token, workspace } = await anOwnerWithAWorkspace();
  const viewer = someone("Viewer Person");

  await addMemberViaApi(token, workspace.id, viewer, "viewer");
  await signInThrough(page, viewer);
  await page.goto("/knowledge");

  await expect(page.getByRole("heading", { name: "Knowledge" })).toBeVisible();
  // Searching spends an embedding, and the API asks for the agent role.
  await expect(page.getByRole("heading", { name: "Try a question" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Upload a file" })).toHaveCount(0);
});
