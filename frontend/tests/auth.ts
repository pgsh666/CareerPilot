import { expect, type Page } from "@playwright/test";
export async function signInPreview(page: Page) {
  await page.goto("/#/login?form=login");
  await page.getByLabel("邮箱", { exact: true }).fill("user@example.com");
  await page.getByLabel("密码", { exact: true }).fill("Pilot@2026");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/#\/home$/);
  await expect(page.locator(".entry-snapshot")).toHaveCount(0);
  await expect(page.locator(".application-shell")).toHaveCSS(
    "transform",
    "none",
  );
}
