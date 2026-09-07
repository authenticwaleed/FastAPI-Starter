import { expect, test, type Page } from "@playwright/test";

import {
  addMemberViaApi,
  createContactViaApi,
  createWorkspaceViaApi,
  registerViaApi,
  signInThrough,
  somePhone,
  someone,
} from "./support";

function slug() {
  return `w6-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
}

async function anOwnerWithAWorkspace() {
  const person = someone("Ada Okonkwo");
  const token = await registerViaApi(person);
  const workspace = await createWorkspaceViaApi(token, slug());

  return { person, token, workspace };
}

async function addProduct(page: Page, name: string, price?: string) {
  await page.goto("/products");
  await page.getByLabel("Name", { exact: true }).fill(name);
  if (price) await page.getByLabel("Price").fill(price);
  await page.getByRole("button", { name: "Add product" }).click();
  await expect(page).toHaveURL(/\/products\/[0-9a-f-]+$/);
}

test("a product needs only a name, and renders without the rest", async ({
  page,
}) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await addProduct(page, "Unnamed sketch");

  // The criterion: no SKU, no description, no price. Somebody sketching a
  // catalogue types six names and comes back for the details.
  await expect(
    page.getByRole("heading", { name: "Unnamed sketch" }),
  ).toBeVisible();
  await expect(page.getByRole("main")).toContainText("—");
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);

  await page.goto("/products");
  await expect(page.getByTestId("product-list")).toContainText("Unnamed sketch");
});

test("a price survives the round trip without becoming a float", async ({
  page,
}) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  // 19.99 is not representable in binary floating point. Anything that
  // parsed it on the way in or out would show 19.989999999999998, or a
  // total built from it would be wrong later.
  await addProduct(page, "Precise item", "19.99");

  await expect(page.getByRole("main")).toContainText("19.99");
  await expect(page.getByRole("main")).not.toContainText("19.98");

  // And the edit form holds the same string, not a re-rendered number.
  await expect(page.getByLabel("Price")).toHaveValue("19.99");
});

test("stock that is not tracked is not zero", async ({ page }) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await page.goto("/products");
  await page.getByLabel("Name", { exact: true }).fill("Boxed set");
  await page.getByRole("button", { name: "Add a variant" }).click();
  await page.getByLabel("Name").last().fill("Large");
  // Stock deliberately left empty.
  await page.getByRole("button", { name: "Add product" }).click();

  await expect(page.getByTestId("variant-list")).toContainText("Stock not tracked");
  await expect(page.getByTestId("variant-list")).not.toContainText("0 in stock");
});

test("saving replaces the variant list, and the form says so", async ({ page }) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  await page.goto("/products");
  await page.getByLabel("Name", { exact: true }).fill("Two sizes");
  await page.getByRole("button", { name: "Add a variant" }).click();
  await page.getByLabel("Name").last().fill("Small");
  await page.getByRole("button", { name: "Add a variant" }).click();
  await page.getByLabel("Name").last().fill("Large");
  await page.getByRole("button", { name: "Add product" }).click();

  await expect(page.getByTestId("variant-list")).toContainText("Small");
  await expect(page.getByTestId("variant-list")).toContainText("Large");
  await expect(page.getByText(/Saving replaces the whole list/)).toBeVisible();

  // Remove one and save: the set is replaced rather than merged, which is
  // the API's rule and has to be what the screen actually does.
  //
  // The row is named rather than taken by position. The API does not
  // promise an order for variants, so "the last one" is not the same row
  // on every read -- which made this pass alone and fail in a full run.
  await page
    .locator("[data-variant-row]")
    .filter({ has: page.locator('input[name="variant_title"][value="Large"]') })
    .getByRole("button", { name: "Remove this variant" })
    .click();
  await page.getByRole("button", { name: "Save" }).click();

  await expect(page.getByRole("status")).toHaveText("Saved.");
  await page.reload();
  await expect(page.getByTestId("variant-list")).toContainText("Small");
  await expect(page.getByTestId("variant-list")).not.toContainText("Large");
});

test("confirming an order twice is safe and says what happened", async ({
  page,
}) => {
  const { person, token, workspace } = await anOwnerWithAWorkspace();

  await createContactViaApi(token, workspace.id, somePhone(), "Rana Customer");
  await signInThrough(page, person);

  await page.goto("/orders");
  await page.getByLabel("Order number").fill("SO-1001");
  await page.getByLabel("Total", { exact: true }).fill("49.50");
  await page.getByRole("button", { name: "Record order" }).click();

  await expect(page).toHaveURL(/\/orders\/[0-9a-f-]+$/);
  await expect(page.getByRole("main")).toContainText("49.50");

  await page.getByRole("button", { name: "Confirm this order" }).click();

  // Confirming is a step forward, not a way to undo a cancellation, so the
  // button is gone rather than sitting there waiting to be refused.
  await expect(page.getByTestId("confirm-note")).toContainText(
    "cannot be confirmed again",
  );
  await expect(
    page.getByRole("button", { name: "Confirm this order" }),
  ).toHaveCount(0);
});

test("an order with no totals shows dashes rather than zeroes", async ({
  page,
}) => {
  const { person, token, workspace } = await anOwnerWithAWorkspace();

  await createContactViaApi(token, workspace.id, somePhone(), "Rana Customer");
  await signInThrough(page, person);

  await page.goto("/orders");
  await page.getByLabel("Order number").fill("SO-1002");
  await page.getByRole("button", { name: "Record order" }).click();

  // An order recorded without a subtotal has none. "0.00" would state a
  // figure nobody entered.
  const totals = page.getByRole("main").locator("dl");

  await expect(totals).toContainText("—");
  await expect(totals).not.toContainText("0.00");
});

test("an order cannot be moved to a different customer", async ({ page }) => {
  const { person, token, workspace } = await anOwnerWithAWorkspace();

  await createContactViaApi(token, workspace.id, somePhone(), "Rana Customer");
  await signInThrough(page, person);

  await page.goto("/orders");
  await page.getByLabel("Order number").fill("SO-1003");
  await page.getByRole("button", { name: "Record order" }).click();

  // Not an omission: moving an order to a different person is a correction
  // of who it was ever for, and the API leaves it out of the update schema
  // so it cannot happen through a PATCH nobody notices.
  await expect(page.getByLabel("Customer")).toHaveCount(0);
  await expect(page.getByLabel("Status")).toBeVisible();
});

test("an agent takes orders but does not edit the catalogue", async ({ page }) => {
  const { token, workspace } = await anOwnerWithAWorkspace();
  const agent = someone("Agent Person");

  await createContactViaApi(token, workspace.id, somePhone(), "Rana Customer");
  await addMemberViaApi(token, workspace.id, agent, "agent");
  await signInThrough(page, agent);

  // Taking an order is customer work, so an agent keeps it.
  await page.goto("/orders");
  await expect(page.getByRole("heading", { name: "Take an order" })).toBeVisible();

  // Changing what the business sells is not.
  await page.goto("/products");
  await expect(page.getByRole("heading", { name: "Add a product" })).toHaveCount(0);
});

test("a viewer reads the catalogue and changes nothing", async ({ page }) => {
  const { token, workspace } = await anOwnerWithAWorkspace();
  const viewer = someone("Viewer Person");

  await addMemberViaApi(token, workspace.id, viewer, "viewer");
  await signInThrough(page, viewer);

  await page.goto("/products");
  await expect(page.getByRole("heading", { name: "Products" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Add a product" })).toHaveCount(0);

  await page.goto("/orders");
  await expect(page.getByRole("heading", { name: "Take an order" })).toHaveCount(0);
});

test("the product list filters by status", async ({ page }) => {
  const { person } = await anOwnerWithAWorkspace();

  await signInThrough(page, person);
  // Lands on the product's own page, which is where its status lives.
  await addProduct(page, "A live one");

  await page.getByLabel("Status").selectOption("draft");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status")).toHaveText("Saved.");

  await page.goto("/products?status=active");
  await expect(page.getByTestId("product-list")).toHaveCount(0);

  await page.goto("/products?status=draft");
  await expect(page.getByTestId("product-list")).toContainText("A live one");
});
