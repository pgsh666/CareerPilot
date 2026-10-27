import { fileURLToPath } from "node:url";
import { test, expect, type Page } from "@playwright/test";
import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";

interface User {
  email: string;
  password: string;
  id: string;
}
let emails: string[] = [];
function fixture<T = unknown>(body: Record<string, unknown>): Promise<T> {
  return new Promise((resolve, reject) => {
    const child = execFile(
      (process.env.CAREERPILOT_PYTHON || "python"),
      [fileURLToPath(new URL("../../backend/scripts/auth_browser_fixture.py", import.meta.url))],
      { windowsHide: true, timeout: 15000 },
      (error, stdout) => {
        if (error) reject(new Error("本地管理测试账号准备或清理失败"));
        else {
          try {
            resolve(JSON.parse(stdout));
          } catch {
            reject(new Error("测试辅助程序返回异常"));
          }
        }
      },
    );
    child.stdin?.end(JSON.stringify(body));
  });
}
async function account(role = "user"): Promise<User> {
  const email = `browser-auth-${randomUUID().replaceAll("-", "")}-a@example.org`;
  emails.push(email);
  return fixture({ action: "prepare", email, role });
}
async function login(page: Page, user: User) {
  await page.goto("/#/login?form=login");
  await page.getByLabel("邮箱", { exact: true }).fill(user.email);
  await page.getByLabel("密码", { exact: true }).fill(user.password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/#\/home$/);
  await expect(page.locator(".entry-snapshot")).toHaveCount(0);
}
test.beforeEach(() => {
  emails = [];
});
test.afterEach(async () => {
  if (emails.length) await fixture({ action: "cleanup", emails });
});
test("管理员实际搜索和启停用户，旧登录立即失效，重新启用后可登录", async ({
  page,
  browser,
}) => {
  const admin = await account("admin"),
    candidate = await account();
  const victim = await browser.newContext();
  try {
    const personal = await victim.newPage();
    await login(personal, candidate);
    await login(page, admin);
    await page.goto("/#/admin");
    await page.getByLabel("搜索用户名或邮箱").fill(candidate.email);
    await expect(page.locator(".admin-user-rows .data-row")).toHaveCount(1);
    await expect(page.locator(".admin-user-rows .data-row small")).toHaveText(
      candidate.email,
    );
    await page.getByRole("button", { name: "查看", exact: true }).click();
    await expect(page.getByRole("dialog")).toContainText(candidate.email);
    await expect(page.getByRole("dialog")).not.toContainText("password_hash");
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "关闭", exact: true })
      .click();
    await page.getByRole("button", { name: "停用", exact: true }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "确认", exact: true })
      .click();
    await expect(page.locator(".admin-user-rows .ui-badge")).toHaveText(
      "已停用",
    );
    await personal.reload();
    await expect(personal).toHaveURL(/#\/login/);
    await page.getByRole("button", { name: "启用", exact: true }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "确认", exact: true })
      .click();
    await expect(page.locator(".admin-user-rows .ui-badge")).toHaveText(
      "已启用",
    );
    await login(personal, candidate);
    expect((await personal.request.get("/api/v1/admin/users")).status()).toBe(
      403,
    );
    await page.getByLabel("搜索用户名或邮箱").fill(admin.email);
    await expect(page.locator(".admin-user-rows .data-row")).toHaveCount(1);
    await expect(page.getByText("当前账号", { exact: true })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "停用", exact: true }),
    ).toHaveCount(0);
  } finally {
    await victim.close();
  }
});
