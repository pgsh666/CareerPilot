import { test, expect, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";
import { signInPreview } from "./auth";

async function submit(page: Page, email = "user@example.com") {
  await page.getByLabel("邮箱", { exact: true }).fill(email);
  await page.getByLabel("密码", { exact: true }).fill("Pilot@2026");
  await page.getByRole("button", { name: "登录", exact: true }).click();
}
async function pauseEntry(page: Page) {
  await expect(page.locator(".entry-snapshot")).toHaveCount(1);
  return page.evaluate(() => {
    const outgoing = document.querySelector<HTMLElement>(".entry-snapshot")!;
    const incoming = document.querySelector<HTMLElement>(
      ".entry-viewport > .application-shell",
    )!;
    for (const element of [incoming, outgoing])
      for (const animation of element.getAnimations()) {
        animation.pause();
        animation.currentTime = 400;
      }
    return {
      incoming: new DOMMatrixReadOnly(getComputedStyle(incoming).transform).m41,
      outgoing: new DOMMatrixReadOnly(getComputedStyle(outgoing).transform).m41,
      opacity: [incoming, outgoing].map(
        (element) => getComputedStyle(element).opacity,
      ),
      duration: incoming.getAnimations()[0]!.effect!.getTiming().duration,
      inert: outgoing.inert,
      hidden: outgoing.getAttribute("aria-hidden"),
      password:
        outgoing.querySelector<HTMLInputElement>('[name="password"]')?.value,
      overflow: document.documentElement.scrollWidth - innerWidth,
    };
  });
}
async function finishEntry(page: Page) {
  await page.evaluate(() => {
    for (const element of document.querySelectorAll(
      ".entry-snapshot, .entry-viewport > .application-shell",
    ))
      element.getAnimations().forEach((animation) => animation.finish());
  });
  await expect(page.locator(".entry-snapshot")).toHaveCount(0);
  await expect(page.locator(".application-shell")).toHaveCSS(
    "transform",
    "none",
  );
}

test("登录成功以900ms连续滑动进入首页，登录画面退出期间不可交互且不重复进场", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/#/login?form=login");
  await submit(page);
  await expect(page).toHaveURL(/#\/home$/);
  const sample = await pauseEntry(page);
  expect(sample.incoming).toBeGreaterThan(0);
  expect(sample.outgoing).toBeLessThan(0);
  expect(sample.opacity).toEqual(["1", "1"]);
  expect(sample.duration).toBe(900);
  expect(sample.inert).toBe(true);
  expect(sample.hidden).toBe("true");
  expect(sample.password).toBe("");
  expect(sample.overflow).toBe(0);
  await expect(page.locator(".route-snapshot")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "登录", exact: true }),
  ).toHaveCount(0);
  await mkdir("../artifacts/login-transition", { recursive: true });
  await page.screenshot({ path: "../artifacts/login-transition/midpoint.png" });
  await finishEntry(page);
  await expect(page.locator(".auth-page")).toHaveCount(0);
  await expect(page.locator(".home-carousel")).toBeVisible();
  const nav = (await page
    .getByRole("navigation", { name: "主导航" })
    .boundingBox())!;
  expect(nav.y).toBe(804);
  expect(nav.height).toBe(72);
  expect(errors).toEqual([]);
});

test("错误登录不切换，减少动态效果时成功登录立即显示目标页面", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/#/login?form=login&redirect=%2Fadmin");
  await page.getByLabel("邮箱", { exact: true }).fill("admin@example.com");
  await page.getByLabel("密码", { exact: true }).fill("wrong-password");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("邮箱或密码不正确");
  await expect(page.locator(".entry-snapshot")).toHaveCount(0);
  await submit(page, "admin@example.com");
  await expect(page).toHaveURL(/#\/admin$/);
  await expect(page.locator(".entry-snapshot")).toHaveCount(0);
  await expect(page.locator(".application-shell")).toHaveCSS(
    "transform",
    "none",
  );
  expect(
    await page
      .locator(".application-shell")
      .evaluate((element) => element.getAnimations().length),
  ).toBe(0);
  await expect(
    page.getByRole("heading", { name: "管理中心", exact: true }),
  ).toBeVisible();
});

test("进场中切换业务页与改变窗口可收尾，后续业务切换仍保留顶部和底栏", async ({
  page,
}) => {
  await page.goto("/#/login?form=login");
  await submit(page);
  await pauseEntry(page);
  const shell = await page.locator(".application-shell").elementHandle();
  const header = await page.locator(".home-header").elementHandle();
  const nav = page.getByRole("navigation", { name: "主导航" });
  const originalNav = await nav.elementHandle();
  await nav
    .getByRole("link", { name: "简历", exact: true })
    .evaluate((element) => (element as HTMLElement).click());
  await expect(page).toHaveURL(/#\/resumes$/);
  expect(await shell!.evaluate((element) => element.isConnected)).toBe(true);
  await page.setViewportSize({ width: 1366, height: 768 });
  await expect(page.locator(".entry-snapshot")).toHaveCount(0);
  await expect(page.locator(".route-snapshot")).toHaveCount(0);
  await expect(page.locator(".application-shell")).toHaveCSS(
    "transform",
    "none",
  );
  const headerBox = await header!.boundingBox(),
    navBox = await nav.boundingBox();
  await nav.getByRole("link", { name: "历史", exact: true }).click();
  await expect(page.locator(".route-snapshot")).toHaveCount(1);
  await expect(page.locator(".entry-snapshot")).toHaveCount(0);
  expect(await header!.evaluate((element) => element.isConnected)).toBe(true);
  expect(await originalNav!.evaluate((element) => element.isConnected)).toBe(
    true,
  );
  expect(await header!.boundingBox()).toEqual(headerBox);
  expect(await nav.boundingBox()).toEqual(navBox);
  await expect(page.locator(".route-snapshot")).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - innerWidth,
    ),
  ).toBe(0);
});


