import { defineConfig } from "@playwright/test";
const port = Number(process.env.CAREERPILOT_UI_TEST_PORT || "5176");
export default defineConfig({
  testDir: "./tests",
  testMatch: ["operation-details.spec.ts", "presentation-polish.spec.ts", "job-rename.spec.ts"],
  timeout: 30_000,
  workers: 1,
  reporter: "list",
  outputDir: "../artifacts/ui/test-output",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    channel: "chrome",
    headless: true,
    viewport: { width: 1440, height: 900 },
    screenshot: "only-on-failure",
  },
  webServer: {
    command: `npm.cmd run dev -- --port ${port}`,
    env: { VITE_PREVIEW_MODE: "false" },
    url: `http://127.0.0.1:${port}`,
    reuseExistingServer: true,
    timeout: 20_000,
  },
});
