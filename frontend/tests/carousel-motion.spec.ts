import { test, expect } from "@playwright/test";
import { signInPreview } from "./auth";

test("轮播使用完整高度左右滑移，特色卡片在动画中不会挤压，其他区域不移动", async ({
  page,
}) => {
  await signInPreview(page);
  const cards = await page.locator(".home-cards").boundingBox();
  const nav = await page.locator(".home-navigation").boundingBox();
  for (const [name, expectedDirection] of [
    ["产品特色", 1],
    ["更新公告", 1],
    ["产品介绍", -1],
  ] as const) {
    await page.getByRole("tab", { name, exact: true }).click();
    await expect(page.locator(".carousel-slide-snapshot")).toHaveCount(1);
    const sample = await page.locator("#home-slide-panel").evaluate((panel) => {
      const incoming = panel.querySelector<HTMLElement>(
        ":scope > .carousel-slide",
      )!;
      const outgoing = panel.querySelector<HTMLElement>(
        ".carousel-slide-snapshot",
      )!;
      for (const element of [incoming, outgoing]) {
        for (const animation of element.getAnimations()) {
          animation.pause();
          animation.currentTime = 400;
        }
      }
      return {
        incomingX: new DOMMatrixReadOnly(getComputedStyle(incoming).transform)
          .m41,
        outgoingX: new DOMMatrixReadOnly(getComputedStyle(outgoing).transform)
          .m41,
        opacity: [incoming, outgoing].map(
          (element) => getComputedStyle(element).opacity,
        ),
        heights: [incoming, outgoing].map(
          (element) => element.getBoundingClientRect().height,
        ),
        panelHeight: panel.getBoundingClientRect().height,
        duration: incoming.getAnimations()[0]!.effect!.getTiming().duration,
        featureHeights: Array.from(
          incoming.querySelectorAll(".capability"),
        ).map((element) => element.getBoundingClientRect().height),
      };
    });
    expect(sample.incomingX * expectedDirection).toBeGreaterThan(0);
    expect(sample.outgoingX * expectedDirection).toBeLessThan(0);
    expect(sample.opacity).toEqual(["1", "1"]);
    expect(sample.duration).toBe(900);
    for (const height of sample.heights)
      expect(height).toBeCloseTo(sample.panelHeight, 0);
    for (const height of sample.featureHeights)
      expect(height).toBeGreaterThan(sample.panelHeight * 0.65);
    expect(await page.locator(".home-cards").boundingBox()).toEqual(cards);
    expect(await page.locator(".home-navigation").boundingBox()).toEqual(nav);
    await page.evaluate(() =>
      document.getAnimations().forEach((animation) => animation.finish()),
    );
    await expect(page.locator(".carousel-slide-snapshot")).toHaveCount(0);
  }
});

test("自动轮播每3秒切换，末屏回到首屏仍沿同一方向", async ({ page }) => {
  const epoch = new Date("2026-10-24T00:00:00Z");
  await page.clock.install({ time: epoch });
  // Freeze before loading: icon initialization must not consume the 100ms
  // margin between the 2900ms assertion and the first 3000ms autoplay tick.
  await page.clock.pauseAt(new Date(epoch.getTime() + 1000));
  await signInPreview(page);
  await page.mouse.move(0, 0);
  await page.clock.fastForward(2900);
  await expect(
    page.getByRole("tab", { name: "产品介绍", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  for (const name of ["产品特色", "更新公告", "产品介绍"]) {
    await page.clock.fastForward(name === "产品特色" ? 100 : 3000);
    await expect(page.getByRole("tab", { name, exact: true })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    const start = await page
      .locator("#home-slide-panel > .carousel-slide")
      .evaluate((element) => {
        const animation = element.getAnimations()[0]!;
        animation.pause();
        animation.currentTime = 0;
        return new DOMMatrixReadOnly(getComputedStyle(element).transform).m41;
      });
    expect(start).toBeGreaterThan(0);
    await page.evaluate(() =>
      document.getAnimations().forEach((animation) => animation.finish()),
    );
    await expect(page.locator(".carousel-slide-snapshot")).toHaveCount(0);
  }
});

test("轮播快速来回切换、离开再进入不会残留或重叠，顶部头像小于品牌Logo", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await signInPreview(page);
  for (const name of ["产品特色", "更新公告", "产品介绍", "产品特色"])
    await page.getByRole("tab", { name, exact: true }).click();
  await expect(page.locator(".carousel-slide-snapshot")).toHaveCount(0);
  await expect(page.locator("#home-slide-panel > .carousel-slide")).toHaveCount(
    1,
  );
  await expect(page.locator(".capability")).toHaveCount(3);
  await page
    .getByRole("navigation", { name: "主导航" })
    .getByRole("link", { name: "历史", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "主导航" })
    .getByRole("link", { name: "首页", exact: true })
    .click();
  await expect(
    page.locator(".route-snapshot,.carousel-slide-snapshot"),
  ).toHaveCount(0);
  await expect(page.locator("#home-slide-panel > .carousel-slide")).toHaveCount(
    1,
  );
  const logo = (await page.locator(".brand-logo").boundingBox())!;
  const avatar = (await page.locator(".user-avatar").boundingBox())!;
  expect(avatar.width).toBeLessThan(logo.width);
  expect(avatar.width).toBeCloseTo(42, 0);
  expect(avatar.width).toBeCloseTo(avatar.height, 0);
  expect(errors).toEqual([]);
});
