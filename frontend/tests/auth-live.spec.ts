import { fileURLToPath } from "node:url";
import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdir } from "node:fs/promises";

interface TestUser {
  id: string;
  email: string;
  password: string;
  name: string;
}
let emails: string[] = [];
function address(kind = "a") {
  const email = `browser-auth-${randomUUID().replaceAll("-", "")}-${kind}@example.org`;
  emails.push(email);
  return email;
}
function fixture<T = Record<string, unknown>>(
  body: Record<string, unknown>,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const child = execFile(
      (process.env.CAREERPILOT_PYTHON || "python"),
      [fileURLToPath(new URL("../../backend/scripts/auth_browser_fixture.py", import.meta.url))],
      { windowsHide: true, timeout: 15_000 },
      (error, stdout) => {
        if (error) reject(new Error("本地测试账号准备或清理失败"));
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
async function user(role = "user", name = "联调用户"): Promise<TestUser> {
  return fixture({ action: "prepare", email: address(), role, name });
}
async function login(page: Page, account: TestUser) {
  await page.goto("/#/login?form=login");
  await page.getByLabel("邮箱", { exact: true }).fill(account.email);
  await page.getByLabel("密码", { exact: true }).fill(account.password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/#\/home$/);
  await expect(page.locator(".entry-snapshot")).toHaveCount(0);
}
async function codeFor(
  request: APIRequestContext,
  email: string,
  purpose: "register" | "email_change" | "password_reset" = "register",
) {
  let code = "";
  await expect
    .poll(
      async () => {
        const search = await request.get(
          `http://127.0.0.1:8025/api/v1/search?${new URLSearchParams({ query: `to:${email}` })}`,
        );
        const list = await search.json();
        for (const item of list.messages || []) {
          const response = await request.get(
            `http://127.0.0.1:8025/api/v1/message/${item.ID}`,
          );
          const message = await response.json();
          if (
            !message.To?.some(
              (recipient: { Address: string }) => recipient.Address === email,
            )
          )
            continue;
          if (
            !message.Subject?.includes(
              {
                register: "注册",
                email_change: "更换邮箱",
                password_reset: "重置密码",
              }[purpose],
            )
          )
            continue;
          const match = message.Text?.match(
            /验证码[：:]\s*([0-9]{6})(?![0-9])/,
          );
          if (match) {
            code = match[1];
            return true;
          }
        }
        return false;
      },
      { timeout: 10_000 },
    )
    .toBe(true);
  return code;
}
async function confirmLogout(page: Page) {
  await page.goto("/#/settings");
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(page).toHaveURL(/#\/login\?form=login$/);
}
test.beforeEach(() => {
  emails = [];
});
test.afterEach(async () => {
  if (emails.length) await fixture({ action: "cleanup", emails });
});

test("真实注册、验证码、资料、换绑、改密、找回与退出闭环", async ({
  page,
  request,
}) => {
  const email = address();
  const changed = address("changed");
  let password = `Test-${randomUUID()}!`;
  await page.goto("/");
  await page
    .getByRole("button", { name: "点击 CareerPilot 标志进入登录", exact: true })
    .click();
  await expect(page.locator(".auth-page")).toHaveAttribute(
    "data-state",
    "login",
  );
  await page.getByRole("button", { name: "立即注册", exact: true }).click();
  await page.getByLabel("邮箱", { exact: true }).fill(email);
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByLabel("确认密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "获取验证码", exact: true }).click();
  await expect(page.getByRole("button", { name: /s 后重发/ })).toBeDisabled();
  const code = await codeFor(request, email);
  await page
    .getByLabel("邮箱验证码")
    .fill(code === "000000" ? "111111" : "000000");
  await page.getByRole("button", { name: "注册", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("验证码错误或已失效");
  await page.getByLabel("邮箱验证码").fill(code);
  let registrations = 0;
  page.on("request", (r) => {
    if (r.url().endsWith("/auth/register")) registrations++;
  });
  await page.locator("form").evaluate((form: HTMLFormElement) => {
    form.requestSubmit();
    form.requestSubmit();
  });
  await expect(
    page.getByRole("button", { name: "登录", exact: true }),
  ).toBeVisible();
  expect(registrations).toBe(1);
  await expect(page.locator(".login-panel .form-error")).toContainText(
    "注册成功",
  );
  await login(page, { email, password, id: "", name: "" });
  await expect(page.locator(".training-metrics strong")).toHaveText(["0", "0"]);
  await expect(page.locator(".priority-title")).toHaveText("暂无待复练任务");
  await page.goto("/#/resumes");
  await expect(
    page.getByText("后端开发 · 校招版", { exact: true }),
  ).toHaveCount(0);
  await page.goto("/#/reports/interview-1");
  await expect(
    page.getByRole("heading", { name: "该记录暂无详情" }),
  ).toBeVisible();
  await page.goto("/#/settings");
  await page.getByLabel("用户名", { exact: true }).fill("浏览器联调甲");
  await page.getByRole("button", { name: "保存修改", exact: true }).click();
  await expect(page.locator(".user-greeting")).toHaveText("您好，浏览器联调甲");
  await page.getByRole("button", { name: "更换头像", exact: true }).click();
  await page.getByRole("button", { name: "使用默认头像", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(page.locator('.user-avatar [data-icon="user"]')).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("用户名", { exact: true })).toHaveValue(
    "浏览器联调甲",
  );
  await page.getByRole("button", { name: "更换绑定邮箱", exact: true }).click();
  await page.getByLabel("新邮箱", { exact: true }).fill(changed);
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "获取验证码", exact: true })
    .click();
  await page
    .getByLabel("邮箱验证码")
    .fill(await codeFor(request, changed, "email_change"));
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(page).toHaveURL(/#\/login\?form=login$/);
  await login(page, { email: changed, password, id: "", name: "" });
  await expect(page.locator(".user-greeting")).toHaveText("您好，浏览器联调甲");
  await page.goto("/#/settings");
  await page.getByRole("button", { name: "修改密码", exact: true }).click();
  const nextPassword = `Changed-${randomUUID()}!`;
  await page.getByLabel("当前密码", { exact: true }).fill("wrong-password");
  await page.getByLabel("新密码", { exact: true }).fill(nextPassword);
  await page.getByLabel("确认新密码", { exact: true }).fill(nextPassword);
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText(
    "当前密码不正确",
  );
  await page.getByLabel("当前密码", { exact: true }).fill(password);
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(page).toHaveURL(/#\/login\?form=login$/);
  password = nextPassword;
  await page.getByRole("button", { name: "忘记密码？", exact: true }).click();
  await page.getByLabel("邮箱", { exact: true }).fill(changed);
  await page.getByRole("button", { name: "获取验证码", exact: true }).click();
  const reset = `Reset-${randomUUID()}!`;
  await page.getByLabel("新密码", { exact: true }).fill(reset);
  await page.getByLabel("确认密码", { exact: true }).fill(reset);
  await page
    .getByLabel("邮箱验证码")
    .fill(await codeFor(request, changed, "password_reset"));
  await page.getByRole("button", { name: "找回密码", exact: true }).click();
  await expect(page.locator(".login-panel .form-error")).toContainText(
    "密码已重置",
  );
  await login(page, { email: changed, password: reset, id: "", name: "" });
  const stored = await page.evaluate(() => JSON.stringify({ ...localStorage }));
  expect(stored).not.toContain(reset);
  expect(stored).not.toContain(nextPassword);
  const cookie = (await page.context().cookies()).find(
    (c) => c.name === (process.env.CAREERPILOT_TEST_COOKIE_NAME || "careerpilot_session"),
  )!;
  expect(cookie.httpOnly).toBe(true);
  expect(stored).not.toContain(cookie.value);
  await mkdir("../artifacts/account-integration", { recursive: true });
  await page.screenshot({
    path: "../artifacts/account-integration/real-home.png",
  });
  await confirmLogout(page);
  await page.goto("/#/history");
  await expect(page).toHaveURL(/#\/login/);
});

test("浏览器伪造登录和管理员缓存不能进入业务页", async ({ page }) => {
  await page.goto("/#/login?form=login");
  await page.evaluate(() => {
    const account = {
      id: "forged",
      email: "admin@example.com",
      name: "伪造管理员",
      avatar: "admin",
      role: "admin",
    };
    localStorage.setItem(
      "careerpilot:frontend:v2",
      JSON.stringify({
        schema: 2,
        signedIn: true,
        account,
        resumes: [],
        jobs: [],
        runs: [],
      }),
    );
    localStorage.setItem(
      "careerpilot:service:v1",
      JSON.stringify({ schema: 1, signedIn: true, account, accounts: {} }),
    );
  });
  await page.goto("/#/admin");
  await expect(page).toHaveURL(/#\/login/);
  await expect(page.locator(".admin-layout")).toHaveCount(0);
  await page.goto("/#/login?form=login");
  await page.getByLabel("邮箱", { exact: true }).fill("admin@example.com");
  await page.getByLabel("密码", { exact: true }).fill("Pilot@2026");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("邮箱或密码不正确");
});

test("账号服务失败保留错误且不会回退到演示登录", async ({ page }) => {
  await page.route("**/api/v1/auth/login", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        error: { code: "UNAVAILABLE", message: "账号服务暂不可用" },
      }),
    }),
  );
  await page.goto("/#/login?form=login");
  await page.getByLabel("邮箱", { exact: true }).fill("user@example.com");
  await page.getByLabel("密码", { exact: true }).fill("Pilot@2026");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("账号服务暂不可用");
  await expect(page).toHaveURL(/#\/login/);
  await expect(page.locator(".home-dashboard")).toHaveCount(0);
});

test("退出请求失败时保留有效登录并允许重试", async ({ page }) => {
  const account = await user();
  await login(page, account);
  await page.goto("/#/settings");
  await page.route("**/api/v1/auth/logout", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        error: { code: "UNAVAILABLE", message: "退出暂不可用" },
      }),
    }),
  );
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText(
    "退出暂不可用",
  );
  await expect(page).toHaveURL(/#\/settings$/);
  expect((await page.request.get("/api/v1/auth/me")).status()).toBe(200);
  await page.unroute("**/api/v1/auth/logout");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(page).toHaveURL(/#\/login\?form=login$/);
});

test("服务端会话过期后不能通过刷新或缓存恢复登录", async ({ page }) => {
  const account = await user();
  await login(page, account);
  await page.goto("/#/interview");
  await page.getByLabel("粘贴岗位JD原文").fill("本人未提交的岗位草稿");
  await fixture({ action: "expire", email: account.email });
  await page
    .getByRole("navigation", { name: "主导航" })
    .getByRole("link", { name: "历史", exact: true })
    .click();
  await expect(page).toHaveURL(/#\/login/);
  await page.reload();
  await expect(page.locator(".application-shell")).toHaveCount(0);
  await login(page, account);
  await page.goto("/#/interview");
  await expect(page.getByLabel("粘贴岗位JD原文")).toHaveValue(
    "本人未提交的岗位草稿",
  );
});

test("跨标签切换账号与退出同步，不显示上一人的草稿", async ({
  page,
  context,
}) => {
  const first = await user("user", "标签用户甲");
  const second = await user("user", "标签用户乙");
  await login(page, first);
  await page.goto("/#/interview");
  await page.getByLabel("粘贴岗位JD原文").fill("甲的私有岗位草稿");
  const other = await context.newPage();
  await login(other, second);
  await expect(page.locator(".user-greeting")).toHaveText("您好，标签用户乙");
  await expect(page.getByLabel("粘贴岗位JD原文")).toHaveValue("");
  await expect(page.locator(".route-snapshots")).not.toContainText(
    "甲的私有岗位草稿",
  );
  await other.goto("/#/interview");
  await other.getByLabel("粘贴岗位JD原文").fill("乙的新岗位草稿");
  await confirmLogout(other);
  await expect(page).toHaveURL(/#\/login/);
  await login(page, first);
  await page.goto("/#/interview");
  await expect(page.getByLabel("粘贴岗位JD原文")).toHaveValue(
    "甲的私有岗位草稿",
  );
  await login(page, second);
  await page.goto("/#/interview");
  await expect(page.getByLabel("粘贴岗位JD原文")).toHaveValue("乙的新岗位草稿");
});

test("切换账号后迟到的资料保存响应不覆盖新账号", async ({ page, context }) => {
  const first = await user("user", "响应用户甲");
  const second = await user("user", "响应用户乙");
  await login(page, first);
  await page.goto("/#/settings");
  let release!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve));
  let received!: () => void;
  const fetched = new Promise<void>((resolve) => (received = resolve));
  await page.route("**/api/v1/account/profile", async (route) => {
    const response = await route.fetch();
    received();
    await gate;
    await route.fulfill({ response });
  });
  await page.getByLabel("用户名", { exact: true }).fill("稍后完成的甲");
  await page.getByRole("button", { name: "保存修改", exact: true }).click();
  await fetched;
  const other = await context.newPage();
  try {
    await login(other, second);
    await expect(page.locator(".user-greeting")).toHaveText("您好，响应用户乙");
  } finally {
    release();
  }
  await expect(page.getByLabel("用户名", { exact: true })).toHaveValue(
    "响应用户乙",
  );
  await page.reload();
  await expect(page.locator(".user-greeting")).toHaveText("您好，响应用户乙");
});

test("管理员角色来自服务端，退出实际撤销认证", async ({ page }) => {
  const account = await user("admin", "管理员");
  await login(page, account);
  await page
    .getByRole("navigation", { name: "主导航" })
    .getByRole("link", { name: "设置", exact: true })
    .click();
  await expect(page).toHaveURL(/#\/admin$/);
  await expect(page.locator(".user-greeting")).toHaveText("管理员");
  await expect(page.locator(".admin-stats")).not.toContainText("12.60");
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(page).toHaveURL(/#\/login\?form=login$/);
  expect((await page.request.get("/api/v1/auth/me")).status()).toBe(401);
});
