import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

/**
 * The pure half of the suite.
 *
 * Vitest covers what can be decided without a browser -- the code-to-
 * sentence map, the shapes read off a failed response. Everything a person
 * would actually see is Playwright's, in `e2e/`, which is why that
 * directory is excluded here rather than left to fail confusingly.
 */
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL(".", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    include: ["**/*.test.ts"],
    exclude: ["node_modules/**", ".next/**", "e2e/**"],
  },
});
