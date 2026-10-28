import { test, expect, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";

const stamp = "2026-10-27T00:30:00Z";
const image =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aVNcAAAAASUVORK5CYII=";
async function mock(page: Page, role = "user") {
  let account = {
    id: `polish-${role}`,
    email: `${role}@example.org`,
    name: "合成验收",
    role,
    enabled: true,
    avatar: "default",
    avatarUrl: null as string | null,
  };
  const queries: string[] = [],
    writes: string[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(),
      path = new URL(request.url()).pathname;
    let body: unknown = {};
    if (request.method() !== "GET") writes.push(path);
    if (path.endsWith("/account/avatar") && request.method() === "PUT") {
      account = {
        ...account,
        avatar: "upload_fixture",
        avatarUrl: `data:image/png;base64,${image}`,
      };
      body = { account };
    } else if (
      path.endsWith("/account/profile") &&
      request.method() === "PATCH"
    ) {
      account = { ...account, ...request.postDataJSON(), avatarUrl: null };
      body = { account };
    } else if (path.endsWith("/auth/me"))
      body = { account, csrf_token: "fixture" };
    else if (path.endsWith("/training/trend")) {
      queries.push(request.url());
      body = {
        version: "careerpilot-rubric-v1",
        versions: [
          { id: "careerpilot-rubric-v1-interview-v2", samples: 0 },
          { id: "careerpilot-rubric-v1", samples: 2 },
        ],
        sampleCount: 2,
        dimensions: [
          { id: "api", name: "接口与数据设计" },
          { id: "logic", name: "逻辑表达" },
        ],
        points: [
          { id: "a", at: stamp, values: [50, 75], coverage: 100 },
          { id: "b", at: stamp, values: [75, 100], coverage: 100 },
        ],
        group: { title: "合成岗位", direction: "后端开发", jdVersion: 1 },
      };
    } else if (path.endsWith("/training/summary"))
      body = {
        active: null,
        completedInterviews: 0,
        practiceMinutes: 0,
        minutesState: "visible_answering",
        tasks: [],
      };
    else if (path.endsWith("/training/filters")) body = { targets: [] };
    else if (path.endsWith("/admin/overview")) {
      const bucket = {
        limitMicroCny: 50000000,
        chargedUpperMicroCny: 286641,
        heldMicroCny: 0,
        remainingMicroCny: 49713359,
        sentCalls: 24,
        estimatedMicroCny: 286641,
        verifiedMicroCny: 0,
        unknownHeldMicroCny: 0,
      };
      body = {
        userCount: 1,
        todayTraining: 1,
        pendingJobs: 0,
        successRate: 58.33,
        unknownCalls: 0,
        services: {
          database: "ready",
          email: "reachable",
          speech: "installed",
          model: "configured",
        },
        budgets: {
          month: bucket,
          test: { ...bucket, limitMicroCny: 20000000 },
        },
        allocations: [
          "面试报告",
          "面试出题",
          "简历解析",
          "JD解析",
          "接入测试",
          "追问",
        ].map((label, i) => ({
          purpose: String(i),
          label,
          calls: 4,
          chargedUpperMicroCny: 10000,
        })),
      };
    } else if (path.endsWith("/admin/tasks"))
      body = {
        total: 17,
        items: Array.from({ length: 4 }, (_, i) => ({
          id: `task-${i}`,
          kind: "plan",
          state: i ? "failed" : "succeeded",
          attempts: 2,
          createdAt: stamp,
          durationMs: 5000,
          errorCode: i ? "MODEL_OUTPUT_INVALID" : null,
          errorMessage: null,
        })),
      };
    else if (path.endsWith("/admin/usage"))
      body = {
        total: 24,
        items: Array.from({ length: 4 }, (_, i) => ({
          id: `usage-${i}`,
          purposeLabel: "面试出题",
          model: "deepseek-flash",
          state: "succeeded",
          createdAt: stamp,
          promptTokens: 4519,
          completionTokens: 652,
          chargedUpperMicroCny: 5725,
          durationMs: 5000,
          errorCode: null,
        })),
      };
    else body = { items: [], total: 0, accountCount: 1 };
    return route.fulfill({ json: body });
  });
  return { queries, writes };
}

test("评分说明、首页公告和仅上传头像保持可用", async ({ page }) => {
  const state = await mock(page);
  await mkdir("../artifacts/presentation-polish", { recursive: true });
  await page.goto("/#/history");
  await expect(
    page.getByRole("button", { name: "查看评分说明" }),
  ).toBeVisible();
  await expect(page.locator(".chart-meta,.trend-foot")).toHaveCount(0);
  await expect(page.getByLabel("评分版本", { exact: true })).toHaveCount(0);
  expect(new URL(state.queries[0]!).searchParams.get("scoring_version")).toBe(
    "auto",
  );
  await page.getByRole("button", { name: "查看评分说明" }).click();
  await expect(page.getByRole("dialog")).toContainText("careerpilot-rubric-v1");
  await expect(page.getByRole("dialog")).toContainText("80%");
  await expect(page.locator(".modal-mask")).toHaveCSS("opacity", "1");
  await expect(page.getByRole("dialog")).toHaveCSS("opacity", "1");
  await page.screenshot({
    path: "../artifacts/presentation-polish/评分说明.png",
  });
  await page.getByRole("button", { name: "知道了", exact: true }).click();
  for (const [width, height] of [
    [1440, 900],
    [1920, 1080],
    [1024, 768],
    [2560, 1440],
  ]) {
    await page.setViewportSize({ width, height });
    const gap = await page.locator(".trend-heading").evaluate((element) => {
      const title = element
        .querySelector(".trend-title")!
        .getBoundingClientRect();
      const filters = element
        .querySelector(".history-filters")!
        .getBoundingClientRect();
      return filters.left - title.right;
    });
    expect(gap).toBeGreaterThanOrEqual(0);
    await page.screenshot({
      path: `../artifacts/presentation-polish/历史趋势-${width}x${height}.png`,
    });
  }
  await page.goto("/#/home");
  await page.getByRole("tab", { name: "更新公告", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "面试、报告与语音体验更新" }),
  ).toBeVisible();
  for (const [width, height] of [
    [1440, 900],
    [1920, 1080],
    [1024, 768],
    [2560, 1440],
  ]) {
    await page.setViewportSize({ width, height });
    const fits = await page
      .locator(".announcement-slide")
      .evaluate((element) => {
        const panel = element.getBoundingClientRect();
        const content = element
          .querySelector(".announcement-copy")!
          .getBoundingClientRect();
        return (
          content.right <= panel.right &&
          content.bottom <= panel.bottom &&
          document.documentElement.scrollWidth <= innerWidth
        );
      });
    expect(fits).toBe(true);
    await page.screenshot({
      path: `../artifacts/presentation-polish/首页公告-${width}x${height}.png`,
    });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("button", { name: /查看更新详情/ }).click();
  await expect(page.getByRole("dialog")).toContainText("2026.10.28");
  await expect(page.locator(".modal-mask")).toHaveCSS("opacity", "1");
  await expect(page.getByRole("dialog")).toHaveCSS("opacity", "1");
  await page.screenshot({
    path: "../artifacts/presentation-polish/更新公告详情.png",
  });
  await page.mouse.move(5, 5);
  await page.waitForTimeout(3400);
  await expect(
    page.getByRole("tab", { name: "更新公告", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await page.getByRole("button", { name: "知道了", exact: true }).click();
  await page.goto("/#/settings");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("button", { name: "更换头像", exact: true }).click();
  await expect(page.locator(".avatar-choices")).toHaveCount(0);
  await expect(page.locator(".modal-mask")).toHaveCSS("opacity", "1");
  await expect(page.getByRole("dialog")).toHaveCSS("opacity", "1");
  await page.screenshot({
    path: "../artifacts/presentation-polish/头像上传.png",
  });
  await page
    .getByLabel("选择头像图片")
    .setInputFiles({
      name: "fixture.png",
      mimeType: "image/png",
      buffer: Buffer.from(image, "base64"),
    });
  await expect(page.getByAltText("头像上传预览")).toBeVisible();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "取消", exact: true })
    .click();
  expect(state.writes).toEqual([]);
  await page.getByRole("button", { name: "更换头像", exact: true }).click();
  await page
    .getByLabel("选择头像图片")
    .setInputFiles({
      name: "fixture.png",
      mimeType: "image/png",
      buffer: Buffer.from(image, "base64"),
    });
  await expect(page.getByAltText("头像上传预览")).toBeVisible();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(page.locator(".user-avatar img")).toBeVisible();
  await page.getByRole("button", { name: "更换头像", exact: true }).click();
  await page.getByRole("button", { name: "使用默认头像", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(page.locator('.user-avatar [data-icon="user"]')).toBeVisible();
  expect(state.writes).toEqual([
    "/api/v1/account/avatar",
    "/api/v1/account/profile",
  ]);
});

test("运行概况和模型用量四种尺寸左右分栏，内容不覆盖分页", async ({ page }) => {
  await mock(page, "admin");
  await page.goto("/#/admin");
  await mkdir("../artifacts/presentation-polish", { recursive: true });
  for (const tab of ["运行概况", "模型用量"]) {
    await page.getByRole("tab", { name: tab, exact: true }).click();
    await expect(page.locator(".tab-slide-snapshot")).toHaveCount(0);
    for (const [width, height] of [
      [1440, 900],
      [1920, 1080],
      [1024, 768],
      [2560, 1440],
    ]) {
      await page.setViewportSize({ width, height });
      const geometry = await page.locator(".operations").evaluate((element) => {
        const sidebar = element
          .querySelector(".operations-columns > aside")!
          .getBoundingClientRect();
        const content = element
          .querySelector(".operations-columns > section")!
          .getBoundingClientRect();
        const footer = element
          .querySelector(".list-footer")!
          .getBoundingClientRect();
        return {
          sidebarRight: sidebar.right,
          contentLeft: content.left,
          sidebarTop: sidebar.top,
          contentTop: content.top,
          sidebarBottom: sidebar.bottom,
          contentBottom: content.bottom,
          footerTop: footer.top,
          horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
        };
      });
      expect(geometry.sidebarRight).toBeLessThan(geometry.contentLeft);
      expect(Math.abs(geometry.sidebarTop - geometry.contentTop)).toBeLessThan(
        2,
      );
      expect(geometry.sidebarBottom).toBeLessThanOrEqual(geometry.footerTop);
      expect(geometry.contentBottom).toBeLessThanOrEqual(geometry.footerTop);
      expect(geometry.horizontalOverflow).toBe(false);
      await page.screenshot({
        path: `../artifacts/presentation-polish/${tab}-${width}x${height}.png`,
      });
    }
  }
});
