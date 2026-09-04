import { defineConfig, devices } from "@playwright/test";

/**
 * The half of the suite that needs a browser.
 *
 * Every acceptance criterion W1 is judged on is something a person would
 * see or something a script must not be able to reach, and neither can be
 * decided without a real browser and a real cookie jar.
 *
 * These need the API running as well as this application -- they sign in
 * against it, and a fake would be testing the fake. `pnpm test:e2e` assumes
 * `./run.sh` is up on :8000; CI starts both.
 */
const PORT = Number(process.env.WEB_PORT ?? 3100);

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? "list" : "line",
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    // Built rather than `next dev`: the thing being accepted is what gets
    // deployed, and dev's error overlay and lack of minification have hidden
    // a real failure in more than one project.
    command: `pnpm build && pnpm start --port ${PORT}`,
    url: `http://localhost:${PORT}/sign-in`,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
