import { expect, test, type BrowserContext, type Page } from "@playwright/test";

import { signOutThrough } from "./support";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/session";

/**
 * What W1 is judged on.
 *
 * The first of these is the one the whole arrangement exists for: if a
 * script in this page can read the session, the cookies, the relay and the
 * proxy were all for nothing.
 */

const API = process.env.API_URL ?? "http://localhost:8000";

/** A fresh account per run, so a rerun does not meet its own leftovers. */
function someone() {
  const id = `${Date.now()}-${Math.floor(Math.random() * 10_000)}`;

  return {
    name: "Ada Okonkwo",
    email: `w1-${id}@example.com`,
    password: "a-perfectly-ordinary-password",
  };
}

async function registerThrough(page: Page, person: ReturnType<typeof someone>) {
  await page.goto("/register");
  await page.getByLabel("Your name").fill(person.name);
  await page.getByLabel("Email").fill(person.email);
  await page.getByLabel("Password").fill(person.password);
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(page.getByRole("heading", { name: /Welcome, Ada/ })).toBeVisible();
}

async function cookieNamed(context: BrowserContext, name: string) {
  return (await context.cookies()).find((cookie) => cookie.name === name);
}

test("a signed-out visitor is sent to sign in, and told where they were going", async ({
  page,
}) => {
  await page.goto("/");

  await expect(page).toHaveURL(/\/sign-in\?next=%2F$/);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});

test("nothing about the session is readable from JavaScript", async ({
  page,
  context,
}) => {
  await registerThrough(page, someone());

  // The acceptance criterion, stated the way it matters: not "the cookie is
  // marked httpOnly" but "a script cannot see it". These are the same thing
  // only while the flag is actually set.
  const visible = await page.evaluate(() => document.cookie);

  expect(visible).not.toContain(ACCESS_COOKIE);
  expect(visible).not.toContain(REFRESH_COOKIE);

  // And the browser is holding them, so the absence above is the flag
  // rather than the absence of a session.
  expect((await cookieNamed(context, ACCESS_COOKIE))?.httpOnly).toBe(true);
  expect((await cookieNamed(context, REFRESH_COOKIE))?.httpOnly).toBe(true);
});

test("a wrong password renders one sentence, not a JSON body", async ({ page }) => {
  const person = someone();

  await registerThrough(page, person);
  await signOutThrough(page);

  await page.getByLabel("Email").fill(person.email);
  await page.getByLabel("Password").fill("not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();

  // Scoped to `main`: Next appends its own route announcer to the body with
  // role="alert", and an unscoped query matches that too.
  const alert = page.getByRole("main").getByRole("alert");

  await expect(alert).toBeVisible();
  await expect(alert).toHaveText("That email and password do not match an account.");
  // The failure this guards against is a raw envelope reaching the screen.
  await expect(alert).not.toContainText("code");
  await expect(alert).not.toContainText("{");
});

test("an expired access token refreshes without the person noticing", async ({
  page,
  context,
}) => {
  await registerThrough(page, someone());

  const before = await cookieNamed(context, REFRESH_COOKIE);

  // Exactly what expiry looks like to the next request: the access cookie
  // is gone and the refresh cookie is not. The proxy should treat that as
  // "refresh me" rather than as a sign-out.
  await context.clearCookies({ name: ACCESS_COOKIE });
  await page.goto("/");

  await expect(page.getByRole("heading", { name: /Welcome, Ada/ })).toBeVisible();

  const after = await cookieNamed(context, ACCESS_COOKIE);
  const rotated = await cookieNamed(context, REFRESH_COOKIE);

  expect(after?.value).toBeTruthy();
  // The API rotates, so a refresh that did not change the refresh token
  // means the refresh never happened.
  expect(rotated?.value).not.toBe(before?.value);
});

test("a replayed refresh token ends the session rather than looping", async ({
  page,
  context,
}) => {
  await registerThrough(page, someone());

  const refresh = await cookieNamed(context, REFRESH_COOKIE);

  expect(refresh?.value).toBeTruthy();

  // Spend it behind this application's back, the way a stolen token would
  // be. The copy in the browser is now the replay.
  const spent = await fetch(`${API}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh!.value }),
  });

  expect(spent.ok).toBe(true);

  await context.clearCookies({ name: ACCESS_COOKIE });
  await page.goto("/");

  await expect(page).toHaveURL(/\/sign-in/);
  expect(await cookieNamed(context, REFRESH_COOKIE)).toBeUndefined();
});

test("signing out ends the session at the API, not just in the browser", async ({
  page,
  context,
}) => {
  await registerThrough(page, someone());

  const refresh = await cookieNamed(context, REFRESH_COOKIE);

  await signOutThrough(page);

  expect(await cookieNamed(context, ACCESS_COOKIE)).toBeUndefined();

  // The token is gone from the browser; this is the half that would still
  // work if the action had only cleared cookies.
  const reuse = await fetch(`${API}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh!.value }),
  });

  expect(reuse.status).toBe(401);
});

test("an unconfirmed address is a nudge, never a gate", async ({ page }) => {
  await registerThrough(page, someone());

  // The product is reachable. `email_verified_at` gates nothing in the API,
  // and a client that stood in front of the product would be inventing a
  // rule -- the one thing the plan asks it not to do.
  await expect(page.getByRole("heading", { name: /Welcome, Ada/ })).toBeVisible();
  await expect(page.getByText(/We have not confirmed/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Send the link again" })).toBeVisible();
});

test("a verification link with no token explains itself", async ({ page }) => {
  await page.goto("/verify-email");

  await expect(page.getByRole("heading", { name: "This link is incomplete" })).toBeVisible();
});
