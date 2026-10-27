import { defineConfig } from "@playwright/test";
import auth from "./playwright.auth.config";
export default defineConfig({
  ...auth,
  testMatch: "materials-live.spec.ts",
  outputDir: "../artifacts/material-service/test-output",
  reporter: [
    ["list"],
    [
      "json",
      { outputFile: "../artifacts/material-service/check-results.json" },
    ],
  ],
});
