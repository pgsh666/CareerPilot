import { defineConfig } from "@playwright/test";
import training from "./playwright.training.config";
process.env.CAREERPILOT_TEST_COOKIE_NAME = "careerpilot_qa_session";
export default defineConfig({
  ...training,
  testMatch: ['auth-live.spec.ts', 'materials-live.spec.ts', 'admin-live.spec.ts', 'training-live.spec.ts'],
  outputDir: '../artifacts/service-regression/test-output',
  reporter: [['list'], ['json', { outputFile: '../artifacts/service-regression/check-results.json' }]],
});
