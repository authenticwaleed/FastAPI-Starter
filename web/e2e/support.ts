import { expect, type Page } from "@playwright/test";

/**
 * Fixtures built by talking to the API directly.
 *
 * Deliberately not through the screens. A test about what a viewer sees
 * needs a viewer to exist, and building one through the invitation flow
 * would be testing W4 in order to reach W2 -- so the setup goes straight to
 * the API and only the thing under test goes through the browser.
 */

export const API = process.env.API_URL ?? "http://localhost:8000";

export type Person = { name: string; email: string; password: string };

let counter = 0;

export function someone(name = "Ada Okonkwo"): Person {
  counter += 1;

  return {
    name,
    email: `w2-${Date.now()}-${counter}-${Math.floor(Math.random() * 1000)}@example.com`,
    password: "a-perfectly-ordinary-password",
  };
}

async function call<T>(path: string, init: RequestInit & { token?: string } = {}) {
  const { token, ...rest } = init;

  const response = await fetch(`${API}/api/v1${path}`, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(rest.headers ?? {}),
    },
  });

  if (!response.ok) {
    throw new Error(`${init.method ?? "GET"} ${path} → ${response.status} ${await response.text()}`);
  }

  return (response.status === 204 ? undefined : await response.json()) as T;
}

export async function registerViaApi(person: Person): Promise<string> {
  await call("/auth/register", {
    method: "POST",
    body: JSON.stringify(person),
  });

  const pair = await call<{ access_token: string }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email: person.email, password: person.password }),
  });

  return pair.access_token;
}

export async function createWorkspaceViaApi(
  token: string,
  slug: string,
): Promise<{ id: string; slug: string; name: string }> {
  return call("/workspaces", {
    method: "POST",
    token,
    body: JSON.stringify({ name: slug.replace(/-/g, " "), slug }),
  });
}

/** Put somebody in a workspace with a given role, without touching the UI. */
export async function addMemberViaApi(
  ownerToken: string,
  workspaceId: string,
  invitee: Person,
  role: "admin" | "agent" | "viewer",
): Promise<string> {
  const invitation = await call<{ token: string }>(
    `/workspaces/${workspaceId}/invitations`,
    {
      method: "POST",
      token: ownerToken,
      body: JSON.stringify({ email: invitee.email, role }),
    },
  );

  const inviteeToken = await registerViaApi(invitee);

  await call(`/invitations/${invitation.token}/accept`, {
    method: "POST",
    token: inviteeToken,
  });

  return inviteeToken;
}

/** Sign in through the screens, which is the only way to get the cookies. */
export async function signInThrough(page: Page, person: Person) {
  await page.goto("/sign-in");
  await page.getByLabel("Email").fill(person.email);
  await page.getByLabel("Password").fill(person.password);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByTestId("account-menu")).toBeVisible();
}

export async function registerThrough(page: Page, person: Person) {
  await page.goto("/register");
  await page.getByLabel("Your name").fill(person.name);
  await page.getByLabel("Email").fill(person.email);
  await page.getByLabel("Password").fill(person.password);
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(page.getByTestId("account-menu")).toBeVisible();
}

/**
 * Sign out through the screens.
 *
 * A helper because W2 moved the control: it was a button in the header and
 * is now inside the account menu, and two specs were reaching for it
 * directly.
 */
export async function signOutThrough(page: Page) {
  await page.getByTestId("account-menu").click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/sign-in/);
}
