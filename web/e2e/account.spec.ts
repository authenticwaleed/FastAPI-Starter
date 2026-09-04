import { expect, test } from "@playwright/test";

import {
  createWorkspaceViaApi,
  registerThrough,
  registerViaApi,
  signInThrough,
  someone,
} from "./support";

test("the name can be changed, and the header follows", async ({ page }) => {
  await registerThrough(page, someone());

  await page.goto("/account");
  await page.getByLabel("Name").fill("Renamed Person");
  await page
    .getByRole("form")
    .filter({ hasText: "Details" })
    .getByRole("button", { name: "Save" })
    .or(page.getByRole("button", { name: "Save" }).first())
    .click();

  await expect(page.getByRole("status").first()).toHaveText("Saved.");
  await expect(page.getByTestId("account-menu")).toContainText("Renamed Person");
});

test("the session list marks this device", async ({ page }) => {
  await registerThrough(page, someone());
  await page.goto("/account");

  const rows = page.getByRole("listitem").filter({ hasText: "This device" });

  await expect(rows).toHaveCount(1);
  // Ending the current session is offered, and labelled so nobody does it
  // by accident while meaning to sign out a different browser.
  await expect(page.getByRole("button", { name: "Sign out here" })).toBeVisible();
});

test("a wrong current password is refused with one sentence", async ({ page }) => {
  await registerThrough(page, someone());
  await page.goto("/account");

  await page.getByLabel("Current password").fill("not-the-password");
  await page.getByLabel("New password").fill("another-ordinary-password");
  await page.getByRole("button", { name: "Change password" }).click();

  const alert = page.getByRole("main").getByRole("alert");

  await expect(alert).toHaveText("That is not your current password.");
  await expect(alert).not.toContainText("{");
});

test("changing the password keeps this device signed in", async ({ page }) => {
  const person = someone();

  await registerThrough(page, person);
  await page.goto("/account");

  await page.getByLabel("Current password").fill(person.password);
  await page.getByLabel("New password").fill("a-brand-new-password");
  await page.getByRole("button", { name: "Change password" }).click();

  // The API ends every *other* session on purpose, which is what makes this
  // useful after a scare. A client that signed itself out here would be
  // undoing the one thing the API deliberately preserved.
  await expect(
    page.getByText("Every other device has been signed out"),
  ).toBeVisible();
  await expect(page.getByTestId("account-menu")).toBeVisible();
});

test("signing out everywhere ends this session too", async ({ page }) => {
  await registerThrough(page, someone());
  await page.goto("/account");

  await page.getByRole("button", { name: "Sign out everywhere" }).click();

  // The API is explicit that "everywhere" contains the caller, so a client
  // that stayed on the page would be showing a session that no longer exists.
  await expect(page).toHaveURL(/\/sign-in/);
});

test("deleting the account is refused while you are somebody's only owner", async ({
  page,
}) => {
  const person = someone();
  const token = await registerViaApi(person);

  await createWorkspaceViaApi(token, `w2-${Date.now()}-owner`);
  await signInThrough(page, person);
  await page.goto("/account");

  await page.getByLabel(/Type DELETE to confirm/).fill("DELETE");
  await page.getByRole("button", { name: "Delete my account" }).click();

  // A step to take rather than a wall, so the screen says which step.
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "only owner of a workspace",
  );
  await expect(page.getByText(/give somebody else the owner role/)).toBeVisible();
  await expect(page).toHaveURL(/\/account$/);
});

test("the typed confirmation is required before anything is called", async ({
  page,
}) => {
  await registerThrough(page, someone());
  await page.goto("/account");

  await page.getByLabel(/Type DELETE to confirm/).fill("delete");
  await page.getByRole("button", { name: "Delete my account" }).click();

  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "Type DELETE to confirm",
  );
  await expect(page).toHaveURL(/\/account$/);
});

test("an account with nothing owed can be deleted", async ({ page }) => {
  await registerThrough(page, someone());
  await page.goto("/account");

  await page.getByLabel(/Type DELETE to confirm/).fill("DELETE");
  await page.getByRole("button", { name: "Delete my account" }).click();

  await expect(page).toHaveURL(/\/sign-in/);
});

test("the feed is empty, and the bell carries no badge", async ({ page }) => {
  await registerThrough(page, someone());
  await page.goto("/notifications");

  await expect(page.getByRole("heading", { name: "Notifications" })).toBeVisible();
  await expect(page.getByText("Nothing here.")).toBeVisible();
  // The badge is absent rather than a zero: a badge showing nought is a
  // thing to look at that says there is nothing to look at.
  await expect(page.getByTestId("unread-count")).toHaveCount(0);
  await expect(page.getByTestId("notification-bell")).toHaveAttribute(
    "aria-label",
    "Notifications",
  );
});
