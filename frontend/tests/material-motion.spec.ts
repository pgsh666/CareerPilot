import { test, expect, type Locator, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { signInPreview } from "./auth";

async function go(page: Page, path: string) {
  await page.goto("/#" + path);
  await expect(page.locator(".route-snapshot")).toHaveCount(0);
}
async function settled(page: Page) {
  await expect(
    page.locator('.collapse-region[data-expanding="true"]'),
  ).toHaveCount(0);
}
async function geometry(record: Locator) {
  return record.evaluate((element) => {
    const head = element.firstElementChild!;
    const origin = head.getBoundingClientRect();
    return [
      ...head.querySelectorAll(
        '[data-record-part="layout"], [data-record-part="summary"]',
      ),
    ].map((part) => {
      const rect = part.getBoundingClientRect();
      return {
        x: rect.x - origin.x,
        y: rect.y - origin.y,
        w: rect.width,
        h: rect.height,
        opacity: Number(getComputedStyle(part).opacity),
      };
    });
  });
}
async function toggleAt(record: Locator, name: string, time: number) {
  await record
    .getByRole("button", { name, exact: true })
    .evaluate(async (button) => {
      (button as HTMLButtonElement).click();
      await new Promise(requestAnimationFrame);
    });
  await record.evaluate((element, time) => {
    for (const animation of element.getAnimations({ subtree: true })) {
      animation.pause();
      animation.currentTime = time;
    }
  }, time);
}
async function finish(record: Locator) {
  await record.evaluate((element) =>
    element
      .getAnimations({ subtree: true })
      .forEach((animation) => animation.finish()),
  );
}

test("简历头部首帧、末帧衔接，图标和摘要随展开收起连续变化", async ({
  page,
}) => {
  await signInPreview(page);
  await go(page, "/resumes");
  const record = page.locator(".resume-record").first();
  const before = await geometry(record);
  await toggleAt(record, "校对简历", 0);
  const start = await geometry(record);
  for (let i = 0; i < before.length; i++)
    for (const key of ["x", "y", "w", "h"] as const)
      expect(
        Math.abs(start[i]![key] - before[i]![key]),
        `首帧 ${i} ${key}`,
      ).toBeLessThan(1);
  await record.evaluate((element) =>
    element.getAnimations({ subtree: true }).forEach((animation) => {
      animation.currentTime = 220;
    }),
  );
  const middle = await geometry(record);
  expect(middle[0]!.w).toBeLessThan(before[0]!.w);
  expect(middle[2]!.opacity).toBeGreaterThan(0);
  expect(middle[2]!.opacity).toBeLessThan(1);
  await mkdir("../artifacts/material-motion", { recursive: true });
  await page.screenshot({
    path: "../artifacts/material-motion/resume-midpoint.png",
  });
  await record.evaluate((element) =>
    element.getAnimations({ subtree: true }).forEach((animation) => {
      animation.currentTime = 499;
    }),
  );
  const last = await geometry(record);
  await finish(record);
  await settled(page);
  const after = await geometry(record);
  for (let i = 0; i < after.length; i++)
    for (const key of ["x", "y", "w", "h"] as const)
      expect(
        Math.abs(last[i]![key] - after[i]![key]),
        `末帧 ${i} ${key}`,
      ).toBeLessThan(1);
  await toggleAt(record, "收起校对", 0);
  const closeStart = await geometry(record);
  for (let i = 0; i < after.length; i++)
    for (const key of ["x", "y", "w", "h"] as const)
      expect(
        Math.abs(closeStart[i]![key] - after[i]![key]),
        `收起首帧 ${i} ${key}`,
      ).toBeLessThan(1);
  await record.evaluate((element) =>
    element.getAnimations({ subtree: true }).forEach((animation) => {
      animation.currentTime = 499;
    }),
  );
  const closingLast = await geometry(record);
  await finish(record);
  await settled(page);
  const closingAfter = await geometry(record);
  for (let i = 0; i < closingAfter.length; i++)
    for (const key of ["x", "y", "w", "h"] as const)
      expect(
        Math.abs(closingLast[i]![key] - closingAfter[i]![key]),
        `收起末帧 ${i} ${key}`,
      ).toBeLessThan(1);
  expect(closingAfter).toEqual(before);
});

test("JD在原记录内展开校对与编辑，收起丢弃草稿，保存更新同一记录", async ({
  page,
}) => {
  await signInPreview(page);
  await go(page, "/interview");
  await page.getByRole("button", { name: /历史 JD/ }).click();
  await expect(page.locator(".tab-slide-snapshot")).toHaveCount(0);
  const record = page.locator(".jd-history-row").first();
  const source = (await record.locator("h3").textContent())!;
  await record.getByRole("button", { name: "校对 JD", exact: true }).click();
  await expect(page.locator(".tab-slide-snapshot")).toHaveCount(0);
  await settled(page);
  await expect(record.locator(".jd-compare")).toBeVisible();
  await page.screenshot({ path: "../artifacts/material-motion/jd-expanded.png" });
  await expect(page.locator(".jd-history-row")).toHaveCount(3);
  await record.getByLabel("岗位名称", { exact: true }).fill("未保存的名称");
  await record.getByRole("button", { name: "收起校对", exact: true }).click();
  await settled(page);
  await record.getByRole("button", { name: "校对 JD", exact: true }).click();
  await settled(page);
  await expect(record.getByLabel("岗位名称", { exact: true })).not.toHaveValue(
    "未保存的名称",
  );
  await record.getByLabel("岗位名称", { exact: true }).fill(source + "更新");
  await record.getByLabel("岗位类别", { exact: true }).selectOption("后端开发");
  await record.getByLabel("岗位方向", { exact: true }).fill("Python 后端");
  await record.getByLabel("明确要求", { exact: true }).fill("数据库与接口设计");
  await record.getByRole("button", { name: "确认并保存", exact: true }).click();
  await settled(page);
  await expect(
    record.getByRole("button", { name: "编辑", exact: true }),
  ).toBeVisible();
  await expect(record.locator("h3")).toHaveText(source + "更新");
  await record.getByRole("button", { name: "编辑", exact: true }).click();
  await settled(page);
  await expect(record.getByLabel("岗位名称", { exact: true })).toHaveValue(
    source + "更新",
  );
  await record.getByRole("button", { name: "收起编辑", exact: true }).click();
  await settled(page);
  const second = page.locator(".jd-history-row").nth(1);
  await second.getByRole("button", { name: "编辑", exact: true }).click();
  await settled(page);
  await expect
    .poll(async () =>
      Math.abs(
        (await second.boundingBox())!.y -
          (await page.locator(".jd-history").boundingBox())!.y,
      ),
    )
    .toBeLessThan(2);
  const saved = await page.evaluate(
    () => JSON.parse(localStorage.getItem("careerpilot:frontend:v2")!).jobs,
  );
  expect(saved).toHaveLength(3);
});

test("JD连续切换、减少动态效果及四种桌面尺寸保持可用", async ({ page }) => {
  await signInPreview(page);
  await go(page, "/interview");
  await page.getByRole("button", { name: /历史 JD/ }).click();
  await expect(page.locator(".tab-slide-snapshot")).toHaveCount(0);
  for (const size of [
    { width: 1024, height: 768 },
    { width: 1366, height: 768 },
    { width: 1920, height: 1080 },
    { width: 2560, height: 1440 },
  ]) {
    await page.setViewportSize(size);
    const record = page.locator(".jd-history-row").first();
    await record.getByRole("button", { name: "校对 JD", exact: true }).click();
    await settled(page);
    const row = (await record.boundingBox())!,
      list = (await page.locator(".jd-history").boundingBox())!,
      save = (await record
        .getByRole("button", { name: "确认并保存", exact: true })
        .boundingBox())!;
    expect(Math.abs(row.height - list.height)).toBeLessThan(2);
    expect(save.y + save.height).toBeLessThan(list.y + list.height + 1);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - innerWidth,
      ),
    ).toBe(0);
    await record.getByRole("button", { name: "收起校对", exact: true }).click();
    await settled(page);
  }
  const first = page.locator(".jd-history-row").first();
  await toggleAt(first, "校对 JD", 180);
  const partial = await geometry(first);
  await toggleAt(first, "收起校对", 0);
  const reverseStart = await geometry(first);
  for (let i = 0; i < partial.length; i++)
    for (const key of ["x", "y", "w", "h"] as const)
      expect(Math.abs(partial[i]![key] - reverseStart[i]![key])).toBeLessThan(
        1,
      );
  await finish(first);
  await settled(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await first.getByRole("button", { name: "校对 JD", exact: true }).click();
  await settled(page);
  await expect(first.locator(".jd-compare")).toBeVisible();
});

test("管理运行概况与模型用量统一左侧概况卡片、右侧记录，筛选与详情保留", async ({
  page,
}) => {
  await page.goto("/#/login?form=login");
  await page.getByLabel("邮箱", { exact: true }).fill("admin@example.com");
  await page.getByLabel("密码", { exact: true }).fill("Pilot@2026");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/#\/home$/);
  await go(page, "/admin");
  for (const size of [
    { width: 1024, height: 768 },
    { width: 1366, height: 768 },
    { width: 1920, height: 1080 },
    { width: 2560, height: 1440 },
  ]) {
    await page.setViewportSize(size);
    await page.getByRole("tab", { name: "运行概况", exact: true }).click();
    await expect(page.locator(".tab-slide-snapshot")).toHaveCount(0);
    const card = (await page.locator(".admin-service").boundingBox())!,
      table = (await page.locator(".admin-tasks").boundingBox())!;
    expect(card.x + card.width).toBeLessThan(table.x);
    expect(card.height).toBeCloseTo(table.height, 0);
    await page.getByRole("tab", { name: "模型用量", exact: true }).click();
    await expect(page.locator(".tab-slide-snapshot")).toHaveCount(0);
    expect(await page.locator(".admin-budget").boundingBox()).toEqual(card);
  }
  await page.getByRole("tab", { name: "运行概况", exact: true }).click();
  await expect(page.locator(".tab-slide-snapshot")).toHaveCount(0);
  await page.getByLabel("任务状态", { exact: true }).selectOption("failed");
  await expect(page.locator(".admin-tasks-body .data-row")).toHaveCount(1);
  await page.getByRole("button", { name: "查看详情", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("返回字段不完整");
  await page.getByRole("button", { name: "关闭", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByLabel("任务状态", { exact: true }).selectOption("all");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.screenshot({
    path: "../artifacts/material-motion/admin-overview.png",
  });
});
