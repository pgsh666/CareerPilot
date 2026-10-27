import { defineConfig } from "@playwright/test";
import auth from "./playwright.auth.config";
export default defineConfig({
  ...auth,
  testMatch: "avatar-live.spec.ts",
  outputDir: "../artifacts/avatar-upload/browser-output",
  reporter: [["list"], ["json", { outputFile: "../artifacts/avatar-upload/browser-results.json" }]],
});
