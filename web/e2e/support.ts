import { execFile } from "node:child_process";
import { promisify } from "node:util";

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

export async function createContactViaApi(
  token: string,
  workspaceId: string,
  phone: string,
  name?: string,
): Promise<{ id: string; phone_number: string }> {
  return call(`/workspaces/${workspaceId}/contacts`, {
    method: "POST",
    token,
    body: JSON.stringify({ phone_number: phone, name }),
  });
}

export async function openConversationViaApi(
  token: string,
  workspaceId: string,
  contactId: string,
): Promise<{ id: string }> {
  return call(`/workspaces/${workspaceId}/conversations`, {
    method: "POST",
    token,
    body: JSON.stringify({ contact_id: contactId }),
  });
}

/** Close a thread behind the browser's back, the way a colleague would. */
export async function closeConversationViaApi(
  token: string,
  workspaceId: string,
  conversationId: string,
): Promise<void> {
  await call(`/workspaces/${workspaceId}/conversations/${conversationId}/close`, {
    method: "POST",
    token,
  });
}

/**
 * Promote an account to staff, from a shell.
 *
 * The one fixture here that is not an HTTP call, and it cannot be one:
 * granting platform access is owner-only, so a deployment with no staff at
 * all has no way to produce the first one through its own API. That is the
 * whole reason `app/staff_cli.py` exists, and it is what a real deployment
 * does once before anybody can open the console.
 *
 * Run from the repository root, where the API's own environment lives.
 */
export async function promoteToStaffViaCli(
  email: string,
  role: "support" | "admin" | "owner" = "owner",
): Promise<void> {
  await promisify(execFile)(
    "uv",
    ["run", "python", "-m", "app.staff_cli", "grant", email, "--role", role],
    { cwd: "..", env: { ...process.env, LOG_LEVEL: "WARNING" } },
  );
}

/**
 * Sign in at the console's own door.
 *
 * A second sign-in for the same account, deliberately: the console keeps a
 * session of its own so that the API refusing an idle one does not touch
 * whatever is signed in to Baton itself (§3.5).
 */
export async function signInToConsoleThrough(page: Page, person: Person) {
  await page.goto("/console/sign-in");
  await page.getByLabel("Email").fill(person.email);
  await page.getByLabel("Password").fill(person.password);
  await page.getByRole("button", { name: "Sign in to the console" }).click();

  await expect(page.getByTestId("console-nav")).toBeVisible();
}

/**
 * A read straight from the API, for asserting on what the screens caused.
 *
 * The console's own claim -- that it issues nothing nobody asked for --
 * can only be checked against the platform's audit log, which is the
 * record of every request it made.
 */
export async function readViaApi<T>(path: string, token: string): Promise<T> {
  return call<T>(path, { token });
}

/**
 * Delete an account, which is how a workspace ends up with nobody in it.
 *
 * Refused while the account is the last owner of a *live* workspace, so
 * the workspace has to be closed first. The pair is a real sequence -- a
 * business winds up and its owner leaves -- and it is the only way to
 * produce the empty team this phase has to render.
 */
export async function deleteAccountViaApi(token: string): Promise<void> {
  await call("/account", { method: "DELETE", token });
}

/** Close a workspace the way its owner would: cancelled, with a date on it. */
export async function closeWorkspaceViaApi(
  ownerToken: string,
  workspaceId: string,
): Promise<void> {
  await call(`/workspaces/${workspaceId}`, { method: "DELETE", token: ownerToken });
}

/**
 * Take a staff member's support grant away behind the browser's back.
 *
 * A faithful stand-in for a grant that expires mid-read, and the only one
 * available: the shortest window the API will open is an hour. It is
 * faithful because the API answers unknown, expired and revoked with the
 * same refusal on purpose -- all three mean the same thing to the person
 * asking and lead to the same next step.
 *
 * `DELETE` ends the caller's own grant, so this is sent as the staff
 * member whose window is being closed.
 */
export async function endSupportAccessViaApi(
  staffToken: string,
  workspaceId: string,
): Promise<void> {
  await call(`/admin/workspaces/${workspaceId}/support-access`, {
    method: "DELETE",
    token: staffToken,
  });
}

/** A message in a customer's thread, put there the way a customer would. */
export async function sendMessageViaApi(
  token: string,
  workspaceId: string,
  conversationId: string,
  text: string,
): Promise<{ id: string }> {
  return call(`/workspaces/${workspaceId}/conversations/${conversationId}/messages`, {
    method: "POST",
    token,
    body: JSON.stringify({ text }),
  });
}

/** A number nobody else in the test run will have. */
export function somePhone(): string {
  const tail = String(Math.floor(Math.random() * 90_000_000) + 10_000_000);

  return `+92300${tail}`;
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
