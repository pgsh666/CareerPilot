import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  testMatch: "auth-live.spec.ts",
  outputDir: "../artifacts/account-integration/test-output",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [
    ["list"],
    [
      "json",
      { outputFile: "../artifacts/account-integration/check-results.json" },
    ],
  ],
  use: {
    baseURL: "http://127.0.0.1:5173",
    channel: "chrome",
    headless: true,
    viewport: { width: 1440, height: 900 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command:
        `"${process.env.CAREERPILOT_PYTHON || "python"}" "../backend/manage.py" serve`,
      url: "http://127.0.0.1:8000/health/ready",
      reuseExistingServer: true,
      timeout: 20_000,
    },
    {
      command: `"${process.env.CAREERPILOT_MAILPIT || "mailpit"}"`,
      url: "http://127.0.0.1:8025/",
      reuseExistingServer: true,
      timeout: 15_000,
    },
    {
      command: "npm.cmd run dev",
      env: { VITE_PREVIEW_MODE: "false" },
      url: "http://127.0.0.1:5173",
      reuseExistingServer: true,
      timeout: 20_000,
    },
  ],
});
