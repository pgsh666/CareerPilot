import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  testMatch: "training-live.spec.ts",
  workers: 1,
  fullyParallel: false,
  timeout: 90_000,
  outputDir: "../artifacts/training-service/test-output",
  reporter: [
    ["list"],
    [
      "json",
      { outputFile: "../artifacts/training-service/check-results.json" },
    ],
  ],
  use: {
    baseURL: "http://127.0.0.1:5175",
    channel: "chrome",
    headless: true,
    viewport: { width: 1440, height: 900 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    launchOptions: {
      args: [
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",
        "--autoplay-policy=no-user-gesture-required",
      ],
    },
  },
  webServer: {
    command: "npm.cmd run dev -- --port 5175",
    env: {
      VITE_PREVIEW_MODE: "false",
      CAREERPILOT_API_TARGET: "http://127.0.0.1:8001",
    },
    url: "http://127.0.0.1:5175",
    reuseExistingServer: true,
    timeout: 20_000,
  },
});
