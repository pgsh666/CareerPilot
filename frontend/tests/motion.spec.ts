import { test, expect } from "@playwright/test";
import { signInPreview } from "./auth";

test("自动轮播循环，悬停和键盘操作暂停，离开后恢复", async ({ page }) => {
  await page.clock.install();
  await signInPreview(page);
  await page.mouse.move(0, 0);
  const selected = (name: string) =>
    expect(page.getByRole("tab", { name, exact: true })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  await page.clock.fastForward(3100);
  await selected("产品特色");
  await page.clock.fastForward(3100);
  await selected("更新公告");
  await page.clock.fastForward(3100);
  await selected("产品介绍");
  await page.locator(".home-carousel").hover();
  await page.clock.fastForward(20000);
  await selected("产品介绍");
  await page.mouse.move(0, 0);
  await page.clock.fastForward(3100);
  await selected("产品特色");
  await page.getByRole("tab", { name: "产品特色", exact: true }).focus();
  await page.clock.fastForward(20000);
  await selected("产品特色");
  await page.keyboard.press("ArrowRight");
  await selected("更新公告");
  await page.locator(".continuation-card .card-action").focus();
  await page.clock.fastForward(3100);
  await selected("产品介绍");
});

test("后台标签暂停轮播，恢复后重新计时", async ({ page }) => {
  await page.clock.install();
  await signInPreview(page);
  await page.mouse.move(0, 0);
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      get: () => true,
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.clock.fastForward(20000);
  await expect(
    page.getByRole("tab", { name: "产品介绍", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      get: () => false,
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.clock.fastForward(3100);
  await expect(
    page.getByRole("tab", { name: "产品特色", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
});

test("按钮回弹保留原生点击与禁用状态，导航切换显示滑动反馈", async ({
  page,
}) => {
  await signInPreview(page);
  const tab = page.getByRole("tab", { name: "产品特色", exact: true });
  const box = (await tab.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await expect(tab).toHaveAttribute("data-pressed", "true");
  await page.mouse.up();
  await expect(tab).toHaveAttribute("aria-selected", "true");
  expect(await tab.evaluate((el) => el.getAnimations().length)).toBeGreaterThan(
    0,
  );
  await page
    .getByRole("navigation", { name: "主导航" })
    .getByRole("link", { name: "历史", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "历史记录", exact: true }),
  ).toBeVisible();
  expect(
    await page
      .locator(".navigation-indicator")
      .evaluate((el) => el.getAnimations().length),
  ).toBeGreaterThan(0);
  await page
    .getByRole("navigation", { name: "主导航" })
    .getByRole("link", { name: "面试", exact: true })
    .click();
  await page.getByRole("tab", { name: "模拟面试", exact: true }).click();
  const start = page.getByRole("button", { name: "进入面试", exact: true });
  await expect(start).toBeDisabled();
  const disabledBox = (await start.boundingBox())!;
  await page.mouse.click(
    disabledBox.x + disabledBox.width / 2,
    disabledBox.y + disabledBox.height / 2,
  );
  await expect(start).not.toHaveAttribute("data-pressed", "true");
  await expect(page).toHaveURL(/tab=prepare/);
});

test("减少动态效果时关闭自动轮播与回弹，手动切换仍可用", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.clock.install();
  await signInPreview(page);
  await page.mouse.move(0, 0);
  await page.clock.fastForward(20000);
  await expect(
    page.getByRole("tab", { name: "产品介绍", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  const tab = page.getByRole("tab", { name: "产品特色", exact: true });
  await tab.click();
  await expect(tab).toHaveAttribute("aria-selected", "true");
  expect(await tab.evaluate((el) => el.getAnimations().length)).toBe(0);
  await page
    .getByRole("navigation", { name: "主导航" })
    .getByRole("link", { name: "历史", exact: true })
    .click();
  await expect(page.locator(".route-snapshot")).toHaveCount(0);
  expect(
    await page
      .locator(".route-screen")
      .evaluate((el) => el.getAnimations().length),
  ).toBe(0);
  expect(
    await page
      .locator(".navigation-indicator")
      .evaluate((el) => el.getAnimations().length),
  ).toBe(0);
  await page
    .getByRole("navigation", { name: "主导航" })
    .getByRole("link", { name: "首页", exact: true })
    .click();
  await tab.click();
  await page.mouse.move(0, 0);
  await page.locator(".continuation-card .card-action").focus();
  await page.clock.fastForward(20000);
  await expect(tab).toHaveAttribute("aria-selected", "true");
});

test("页面和导航同向缓动，顶部与底栏保持原位，往返切换没有整页淡出", async ({
  page,
}) => {
  await signInPreview(page);
  const header = await page.locator(".home-header").elementHandle();
  const navigation = await page
    .getByRole("navigation", { name: "主导航" })
    .elementHandle();
  const headerBox = await header!.boundingBox();
  const navigationBox = await navigation!.boundingBox();
  for (const [label, direction] of [
    ["历史", 1],
    ["首页", -1],
  ] as const) {
    await page
      .getByRole("navigation", { name: "主导航" })
      .getByRole("link", { name: label, exact: true })
      .click();
    await expect(page.locator(".route-snapshot")).toHaveCount(1);
    const sample = await page.evaluate(() => {
      const active = document.querySelector<HTMLElement>(
        ".route-screen:not(.route-snapshot)",
      )!;
      const snapshot = document.querySelector<HTMLElement>(".route-snapshot")!;
      const indicator = document.querySelector<HTMLElement>(
        ".navigation-indicator",
      )!;
      for (const el of [active, snapshot, indicator]) {
        for (const animation of el.getAnimations()) {
          animation.pause();
          animation.currentTime = 400;
        }
      }
      return {
        activeX: new DOMMatrixReadOnly(getComputedStyle(active).transform).m41,
        previousX: new DOMMatrixReadOnly(getComputedStyle(snapshot).transform)
          .m41,
        opacity: [active, snapshot].map((el) => getComputedStyle(el).opacity),
        inert: snapshot.inert,
        duration: indicator.getAnimations()[0]!.effect!.getTiming().duration,
      };
    });
    expect(sample.activeX * direction).toBeGreaterThan(0);
    expect(sample.previousX * direction).toBeLessThan(0);
    expect(sample.opacity).toEqual(["1", "1"]);
    expect(sample.inert).toBe(true);
    expect(sample.duration).toBe(900);
    expect(await header!.evaluate((el) => el.isConnected)).toBe(true);
    expect(await navigation!.evaluate((el) => el.isConnected)).toBe(true);
    expect(await header!.boundingBox()).toEqual(headerBox);
    expect(await navigation!.boundingBox()).toEqual(navigationBox);
    await page.evaluate(() =>
      document.getAnimations().forEach((animation) => animation.finish()),
    );
    await expect(page.locator(".route-snapshot")).toHaveCount(0);
  }
});

test("快速连续切换及浏览器后退能完成，动效不残留也不增加滚动条", async ({
  page,
}) => {
  await signInPreview(page);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const nav = page.getByRole("navigation", { name: "主导航" });
  await nav.getByRole("link", { name: "历史", exact: true }).click();
  await nav.getByRole("link", { name: "简历", exact: true }).click();
  await nav.getByRole("link", { name: "设置", exact: true }).click();
  await expect(page.locator(".route-snapshot")).toHaveCount(0);
  await expect(
    nav.getByRole("link", { name: "设置", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  await expect(
    page.getByRole("heading", { name: "账号管理", exact: true }),
  ).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/#\/resumes$/);
  await expect(page.locator(".route-snapshot")).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "我的简历", exact: true }),
  ).toBeVisible();
  const geometry = await page.evaluate(() => ({
    overflow: document.documentElement.scrollWidth - innerWidth,
    animations: document.querySelector(".route-screen")!.getAnimations().length,
    transform: getComputedStyle(document.querySelector(".route-screen")!)
      .transform,
  }));
  expect(geometry).toEqual({ overflow: 0, animations: 0, transform: "none" });
  expect(errors).toEqual([]);
});
