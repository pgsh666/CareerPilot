import { test, expect } from "@playwright/test";
import { signInPreview } from "./auth";
test("默认入口先展示Logo，点击后翻转进入登录，登录后进入首页", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page).toHaveURL(/#\/login$/);
  await expect(page.locator(".auth-page")).toHaveAttribute(
    "data-state",
    "intro",
  );
  await expect(page.locator(".auth-scene")).toHaveAttribute("inert", "");
  await page
    .getByRole("button", { name: "点击 CareerPilot 标志进入登录", exact: true })
    .click();
  await expect(page.locator(".auth-page")).toHaveAttribute(
    "data-state",
    "transition",
  );
  await expect(page.locator(".auth-page")).toHaveAttribute(
    "data-state",
    "login",
  );
  await page.getByLabel("邮箱", { exact: true }).fill("user@example.com");
  await page.getByLabel("密码", { exact: true }).fill("Pilot@2026");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/#\/home$/);
  await expect(page.locator(".home-carousel")).toBeVisible();
  await page
    .getByRole("navigation", { name: "主导航" })
    .getByRole("link", { name: "简历", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "主导航" })
    .getByRole("link", { name: "首页", exact: true })
    .click();
  await expect(page).toHaveURL(/#\/home$/);
  await expect(page.locator(".auth-page")).toHaveCount(0);
});
test("已有演示登录记录时重新打开根地址也显示Logo入口", async ({ page }) => {
  await signInPreview(page);
  await page.goto("/");
  await expect(page.locator(".auth-page")).toHaveAttribute(
    "data-state",
    "intro",
  );
});
test("未登录的业务链接先显示Logo，登录后返回目标页面", async ({ page }) => {
  await page.goto("/#/history");
  await expect(page.locator(".auth-page")).toHaveAttribute(
    "data-state",
    "intro",
  );
  await page
    .getByRole("button", { name: "点击 CareerPilot 标志进入登录", exact: true })
    .click();
  await expect(page.locator('.auth-page')).toHaveAttribute('data-state','login');
  await page.getByLabel("邮箱", { exact: true }).fill("user@example.com");
  await page.getByLabel("密码", { exact: true }).fill("Pilot@2026");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/#\/history$/);
});
