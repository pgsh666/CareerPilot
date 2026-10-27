import { defineConfig } from "@playwright/test";
import auth from "./playwright.auth.config";
export default defineConfig({
  ...auth,
  testMatch: "admin-live.spec.ts",
  outputDir: "../artifacts/admin-service/test-output",
  reporter: [
    ["list"],
    ["json", { outputFile: "../artifacts/admin-service/check-results.json" }],
  ],
});
