import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  testIgnore: ["**/*-live.spec.ts", "**/operation-details.spec.ts", "**/presentation-polish.spec.ts", "**/job-rename.spec.ts"],
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  reporter: [
    ["list"],
    ["json", { outputFile: "../artifacts/frontend-full/check-results.json" }],
  ],
  use: {
    baseURL: "http://127.0.0.1:5174",
    headless: true,
    channel: "chrome",
    viewport: { width: 1440, height: 900 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm.cmd run dev -- --port 5174",
    env: { VITE_PREVIEW_MODE: "true" },
    url: "http://127.0.0.1:5174",
    reuseExistingServer: true,
    timeout: 20_000,
  },
});
