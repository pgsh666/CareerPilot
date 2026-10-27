import { test, expect, type Page } from "@playwright/test";

async function login(page: Page, admin = false) {
  await page.goto("/#/login?form=login");
  await page
    .getByLabel("邮箱", { exact: true })
    .fill(admin ? "admin@example.com" : "user@example.com");
  await page.getByLabel("密码", { exact: true }).fill("Pilot@2026");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/#\/home$/);
}

for (const config of [
  {
    name: "管理中心",
    path: "/admin",
    tablist: "管理功能",
    from: "用户管理",
    to: "模型用量",
    admin: true,
  },
  {
    name: "面试",
    path: "/interview",
    tablist: "面试功能",
    from: "岗位 JD",
    to: "薄弱项复练",
  },
  {
    name: "历史",
    path: "/history",
    tablist: "记录类型",
    from: "模拟面试",
    to: "薄弱项复练",
  },
  {
    name: "简历分类",
    path: "/resumes",
    tablist: "简历字段分类",
    from: "基本信息",
    to: "个人技能",
  },
  {
    name: "面试报告",
    path: "/reports/interview-6",
    tablist: "面试报告内容",
    from: "报告概览",
    to: "维度评分",
  },
  {
    name: "复练详情",
    path: "/practice/practice-3",
    tablist: "复练详情内容",
    from: "原题对照",
    to: "变式验证",
  },
]) {
  test(`${config.name}页签双向滑移，页签栏与页面外框不动`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await login(page, config.admin);
    await page.goto("/#" + config.path);
    await expect(page.locator(".route-snapshot")).toHaveCount(0);
    if (config.path === "/resumes")
      await page.getByRole("button", { name: "校对简历", exact: true }).click();
    await expect(
      page.locator('.collapse-region[data-expanding="true"]'),
    ).toHaveCount(0);
    const tablist = page.getByRole("tablist", {
      name: config.tablist,
      exact: true,
    });
    const tablistBox = await tablist.boundingBox();
    const nav = page.getByRole("navigation", { name: "主导航" });
    const navBox = await nav.boundingBox();
    for (const [label, direction] of [
      [config.to, 1],
      [config.from, -1],
    ] as const) {
      await tablist
        .getByRole("tab", { name: label, exact: config.path !== "/history" })
        .click();
      await expect(page.locator(".tab-slide-snapshot")).toHaveCount(1);
      const sample = await page
        .locator(".tab-slide-viewport")
        .evaluate((viewport) => {
          const active = viewport.querySelector<HTMLElement>(
            ":scope > .tab-slide-pane",
          )!;
          const previous = viewport.querySelector<HTMLElement>(
            ".tab-slide-snapshot",
          )!;
          for (const element of [active, previous]) {
            for (const animation of element.getAnimations()) {
              animation.pause();
              animation.currentTime = 400;
            }
          }
          return {
            incoming: new DOMMatrixReadOnly(getComputedStyle(active).transform)
              .m41,
            outgoing: new DOMMatrixReadOnly(
              getComputedStyle(previous).transform,
            ).m41,
            opacity: [active, previous].map(
              (element) => getComputedStyle(element).opacity,
            ),
            duration: active.getAnimations()[0]!.effect!.getTiming().duration,
            inert: previous.inert,
            overflow: getComputedStyle(viewport).overflowX,
          };
        });
      expect(sample.incoming * direction).toBeGreaterThan(0);
      expect(sample.outgoing * direction).toBeLessThan(0);
      expect(sample.opacity).toEqual(["1", "1"]);
      expect(sample.duration).toBe(900);
      expect(sample.inert).toBe(true);
      expect(sample.overflow).toBe("clip");
      expect(await tablist.boundingBox()).toEqual(tablistBox);
      expect(await nav.boundingBox()).toEqual(navBox);
      await expect(page.locator(".route-snapshot")).toHaveCount(0);
      await page.evaluate(() =>
        document.getAnimations().forEach((animation) => animation.finish()),
      );
      await expect(page.locator(".tab-slide-snapshot")).toHaveCount(0);
    }
    expect(errors).toEqual([]);
  });
}

test("页签快速切换保留筛选、表单草稿，离开页面清除动画副本", async ({
  page,
}) => {
  await login(page, true);
  await page.goto("/#/admin");
  await expect(page.locator(".route-snapshot")).toHaveCount(0);
  const tabs = page.getByRole("tablist", { name: "管理功能", exact: true });
  await page
    .getByRole("searchbox", { name: "搜索用户名或邮箱", exact: true })
    .fill("林");
  for (const name of ["运行概况", "模型用量", "用户管理"])
    await tabs.getByRole("tab", { name, exact: true }).click();
  await expect(page.locator(".tab-slide-snapshot")).toHaveCount(0);
  await expect(
    page.getByRole("searchbox", { name: "搜索用户名或邮箱", exact: true }),
  ).toHaveValue("林");
  await page.goto("/#/resumes");
  await expect(page.locator(".route-snapshot")).toHaveCount(0);
  await page.getByRole("button", { name: "校对简历", exact: true }).click();
  await page.getByRole("tab", { name: "项目经历", exact: true }).click();
  await page.getByLabel("项目名称", { exact: true }).fill("保留的项目草稿");
  await page.getByRole("tab", { name: "基本信息", exact: true }).click();
  await page.getByRole("tab", { name: "项目经历", exact: true }).click();
  await expect(page.locator(".tab-slide-snapshot")).toHaveCount(0);
  await expect(page.getByLabel("项目名称", { exact: true })).toHaveValue(
    "保留的项目草稿",
  );
  await page.getByRole("tab", { name: "个人技能", exact: true }).click();
  await page
    .getByRole("navigation", { name: "主导航" })
    .getByRole("link", { name: "首页", exact: true })
    .click();
  await expect(page.locator(".route-snapshot,.tab-slide-snapshot")).toHaveCount(
    0,
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - innerWidth,
    ),
  ).toBe(0);
});

test("减少动态效果时页签立即切换，原有表单和按钮保持可用", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await login(page, true);
  await page.goto("/#/admin");
  await page.getByRole("tab", { name: "运行概况", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "最近任务", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".tab-slide-snapshot")).toHaveCount(0);
  expect(
    await page
      .locator(".tab-slide-pane")
      .evaluate((element) => element.getAnimations().length),
  ).toBe(0);
  await page.getByRole("tab", { name: "用户管理", exact: true }).click();
  await page
    .getByRole("searchbox", { name: "搜索用户名或邮箱", exact: true })
    .fill("不存在的账号");
  await expect(page.getByText("没有匹配的用户", { exact: true })).toBeVisible();
});
