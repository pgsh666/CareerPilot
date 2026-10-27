import { test, expect } from "@playwright/test";
import { mkdir } from "node:fs/promises";

const created = "2026-10-26T16:32:46Z";
const task = {
  id: "synthetic-task-details",
  kind: "plan",
  state: "succeeded",
  attempts: 2,
  errorCode: null,
  errorMessage: null,
  createdAt: created,
  startedAt: created,
  finishedAt: created,
  durationMs: 5000,
  trainingId: "synthetic-training",
  interviewPolicy: "natural-jd-v2",
  scoringVersion: "careerpilot-rubric-v1-interview-v2",
  outputSaved: true,
  diagnostic: {
    availability: "none",
    stageLabel: null,
    rule: null,
    raw: null,
    reason: "未记录校验失败。",
    issues: [],
  },
};
const calls = [2, 1].map((attempt) => ({
  id: `synthetic-call-${attempt}`,
  purpose: "question",
  purposeLabel: "面试出题",
  taskId: task.id,
  requestKey: `${task.id}-attempt-${attempt}`,
  provider: "deepseek",
  model: "deepseek-flash",
  providerRequestId: `synthetic-provider-${attempt}`,
  attempt,
  state: attempt === 1 ? "failed" : "succeeded",
  createdAt: created,
  finishedAt: created,
  durationMs: 5000,
  promptTokens: 400,
  completionTokens: 100,
  cachedTokens: 10,
  totalTokens: 500,
  chargedUpperMicroCny: 1000 * attempt,
  reservedMicroCny: 2000000,
  feeSource: "peak_upper_estimate",
  testMode: true,
  candidateAvailable: false,
  errorCode: attempt === 1 ? "MODEL_OUTPUT_INVALID" : null,
  diagnostic:
    attempt === 1
      ? {
          availability: "recorded",
          stageLabel: "字段与结构校验",
          rule: "SCHEMA_INVALID",
          reason: "返回内容缺少必要字段，或字段类型、范围不符合约定。",
          issues: [
            {
              path: "questions[2].dimension_ids",
              type: "missing",
              reason: "缺少必填字段",
            },
          ],
          raw: {
            stage: "schema",
            rule: "SCHEMA_INVALID",
            issues: [
              { path: ["questions", 2, "dimension_ids"], type: "missing" },
            ],
          },
        }
      : task.diagnostic,
}));
const detail = {
  task,
  calls,
  callCount: 2,
  chargedUpperMicroCny: 3000,
  unknownCallCount: 0,
  callsTruncated: false,
  selectedCallId: calls[0].id,
  observedAt: created,
};

test("任务详情展示成功状态、历史失败、字段原因和原始诊断，四种尺寸可滚动", async ({
  page,
}) => {
  let detailRequests = 0;
  const writes: string[] = [];
  await page.route("**/api/v1/**", async (route) => {
    if (route.request().method() !== "GET") {
      writes.push(route.request().method());
      return route.abort();
    }
    const path = new URL(route.request().url()).pathname;
    const bucket = {
      limitMicroCny: 50000000,
      chargedUpperMicroCny: 3000,
      heldMicroCny: 0,
      remainingMicroCny: 49997000,
      sentCalls: 2,
    };
    let body: unknown = {};
    if (path.endsWith("/auth/me"))
      body = {
        account: {
          id: "admin-layout",
          email: "admin@example.org",
          name: "合成管理员",
          role: "admin",
          avatar: "default",
          enabled: true,
        },
        csrf_token: "fixture",
      };
    else if (path.endsWith("/admin/users"))
      body = { items: [], total: 0, accountCount: 1 };
    else if (path.endsWith("/admin/overview"))
      body = {
        userCount: 1,
        todayTraining: 1,
        pendingJobs: 0,
        successRate: 50,
        unknownCalls: 0,
        budgets: {
          month: bucket,
          test: { ...bucket, limitMicroCny: 20000000 },
        },
        services: {},
        allocations: [],
      };
    else if (path.endsWith("/admin/tasks")) body = { items: [task], total: 1 };
    else if (path.endsWith("/admin/usage")) body = { items: calls, total: 2 };
    else if (path.includes("/admin/tasks/")) {
      detailRequests++;
      body = detail;
    } else if (path.includes("/admin/usage/"))
      body = { ...detail, selectedCallId: calls[1].id };
    return route.fulfill({ json: body });
  });
  await page.goto("/#/admin");
  await page.getByRole("tab", { name: "运行概况", exact: true }).click();
  await expect(page.locator(".tab-slide-snapshot")).toHaveCount(0);
  await page
    .locator(".operation-row")
    .getByRole("button", { name: "详情", exact: true })
    .click();
  const modal = page.getByRole("dialog", { name: "任务与调用详情" });
  await expect(
    modal.getByText("SCHEMA_INVALID", { exact: false }).first(),
  ).toBeVisible();
  await expect(modal).toContainText("无当前错误");
  await expect(modal).toContainText("MODEL_OUTPUT_INVALID");
  await expect(modal).toContainText("questions[2].dimension_ids");
  await expect(modal).toContainText("后端原始诊断 JSON");
  await modal.getByRole("button", { name: "刷新详情", exact: true }).click();
  await expect.poll(() => detailRequests).toBe(2);
  await mkdir("../artifacts/operation-details", { recursive: true });
  for (const [width, height] of [
    [1440, 900],
    [1920, 1080],
    [1024, 768],
    [2560, 1440],
  ]) {
    await page.setViewportSize({ width, height });
    await modal.locator(".diagnostic-json").first().scrollIntoViewIfNeeded();
    const geometry = await modal.evaluate((element) => {
      const box = element.getBoundingClientRect();
      const body = element.querySelector(".modal-body")!;
      return {
        top: box.top,
        bottom: box.bottom,
        width: box.width,
        viewportHeight: innerHeight,
        viewportWidth: innerWidth,
        bodyOverflow: body.scrollWidth > body.clientWidth + 1,
      };
    });
    expect(geometry.top).toBeGreaterThanOrEqual(0);
    expect(geometry.bottom).toBeLessThanOrEqual(geometry.viewportHeight);
    expect(geometry.width).toBeLessThanOrEqual(geometry.viewportWidth);
    expect(geometry.bodyOverflow).toBe(false);
    await page.screenshot({
      path: `../artifacts/operation-details/${width}x${height}.png`,
    });
  }
  await modal.getByRole("button", { name: "关闭", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("tab", { name: "模型用量", exact: true }).click();
  await expect(page.locator(".tab-slide-snapshot")).toHaveCount(0);
  await page
    .locator(".usage-table .data-row")
    .last()
    .getByRole("button", { name: "详情", exact: true })
    .click();
  await expect(modal).toContainText("synthetic-provider-1");
  expect(writes).toEqual([]);
});
