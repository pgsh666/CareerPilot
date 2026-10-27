import { fileURLToPath } from "node:url";
import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdir, readFile } from "node:fs/promises";

const source =
  "姓名：材料联调\n学校：测试大学\n项目名称：职业助手\n个人职责：实现文件API\n项目内容：处理上传和校对\n项目成果：保存版本\n专业技能：Python、MySQL";
const jd =
  "岗位名称：后端开发工程师\n岗位方向：Python\n公司名称：联调公司\n岗位职责：开发私有材料API\n任职要求：掌握Python和MySQL";
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
        if (error) reject(new Error("本地材料测试账号准备或清理失败"));
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
async function account(): Promise<User> {
  const email = `browser-auth-${randomUUID().replaceAll("-", "")}-a@example.org`;
  emails.push(email);
  return fixture({ action: "prepare", email });
}
async function login(page: Page, user: User) {
  await page.goto("/#/login?form=login");
  await page.getByLabel("邮箱", { exact: true }).fill(user.email);
  await page.getByLabel("密码", { exact: true }).fill(user.password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/#\/home$/);
  await expect(page.locator(".entry-snapshot")).toHaveCount(0);
}
async function upload(page: Page, name = "本人简历.txt", body = source) {
  await page.getByRole("button", { name: "上传简历", exact: true }).click();
  await page
    .getByLabel("选择简历文件")
    .setInputFiles({ name, mimeType: "text/plain", buffer: Buffer.from(body) });
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator(".resume-record")).toHaveCount(1);
}
async function csrf(request: APIRequestContext) {
  const response = await request.get("/api/v1/auth/me");
  return { "X-CSRF-Token": (await response.json()).csrf_token };
}
test.beforeEach(() => {
  emails = [];
});
test.afterEach(async () => {
  if (emails.length) await fixture({ action: "cleanup", emails });
});

test("简历上传提取、确认、独立浏览器恢复、下载、重命名及删除", async ({
  page,
  browser,
}) => {
  const user = await account();
  await login(page, user);
  await page.goto("/#/resumes");
  await upload(page);
  await expect(page.locator(".resume-paper")).toContainText(source);
  await expect(page.getByRole("tab", { name: "基本信息", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "项目经历", exact: true }).click();
  await expect(page.getByLabel("项目名称", { exact: true })).toHaveValue(
    "职业助手",
  );
  await page.getByLabel("个人职责", { exact: true }).fill("校对后的个人职责");
  await page.getByRole("button", { name: "确认并保存", exact: true }).click();
  await expect(page.locator(".resume-record .ui-badge")).toHaveText("已确认");
  const second = await browser.newContext();
  try {
    const other = await second.newPage();
    await login(other, user);
    await other.goto("/#/resumes");
    await expect(other.locator(".resume-record")).toHaveCount(1);
    await other.getByRole("button", { name: "编辑", exact: true }).click();
    await other.getByRole("tab", { name: "项目经历", exact: true }).click();
    await expect(other.getByLabel("个人职责", { exact: true })).toHaveValue(
      "校对后的个人职责",
    );
    await other.getByRole("button", { name: "收起编辑", exact: true }).click();
    await other
      .getByRole("button", { name: "本人简历的更多操作", exact: true })
      .click();
    const download = other.waitForEvent("download");
    await other
      .getByRole("button", { name: "下载原文件", exact: true })
      .click();
    const file = await download;
    expect(
      (await readFile((await file.path())!)).equals(Buffer.from(source)),
    ).toBe(true);
    await other
      .getByRole("button", { name: "本人简历的更多操作", exact: true })
      .click();
    await other.getByRole("button", { name: "重命名", exact: true }).click();
    await other.getByLabel("简历名称").fill("校招材料");
    await other
      .getByRole("dialog")
      .getByRole("button", { name: "确认", exact: true })
      .click();
    await expect(other.locator(".resume-name h2")).toHaveText("校招材料");
    await other
      .getByRole("button", { name: "校招材料的更多操作", exact: true })
      .click();
    await other.getByRole("button", { name: "删除简历", exact: true }).click();
    await other
      .getByRole("dialog")
      .getByRole("button", { name: "删除", exact: true })
      .click();
    await expect(other.locator(".resume-record")).toHaveCount(0);
    await page.reload();
    await expect(page.locator(".resume-record")).toHaveCount(0);
  } finally {
    await second.close();
  }
});

test("JD原文解析、缺项校对、推断选择、保存版本及刷新恢复", async ({ page }) => {
  await login(page, await account());
  await page.goto("/#/interview");
  await page.getByLabel("粘贴岗位JD原文").fill(jd);
  await page.getByRole("button", { name: "解析 JD", exact: true }).click();
  await expect(page.getByLabel("岗位名称", { exact: true })).toHaveValue(
    "后端开发工程师",
  );
  await expect(page.getByLabel("公司名称", { exact: true })).toHaveValue(
    "联调公司",
  );
  await expect(page.getByLabel("明确要求", { exact: true })).toHaveValue(
    "掌握Python和MySQL",
  );
  await expect(page.getByLabel("核心职责", { exact: true })).toHaveValue(
    "开发私有材料API",
  );
  await page.getByRole("button", { name: "确认并保存", exact: true }).click();
  await expect(page.locator(".jd-editor-heading .ui-badge")).toHaveText(
    "已确认",
  );
  await page.reload();
  await page.getByRole("button", { name: /历史 JD/ }).click();
  await expect(page.locator(".jd-history-row")).toHaveCount(1);
  await page.getByRole("button", { name: "编辑", exact: true }).click();
  await page.getByLabel("粘贴岗位JD原文").fill(jd.replace("MySQL", "Redis"));
  await expect(
    page.getByRole("button", { name: "确认并保存", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "解析 JD", exact: true }).click();
  await expect(page.getByLabel("明确要求", { exact: true })).toHaveValue(
    "掌握Python和Redis",
  );
  await page.getByRole("button", { name: "确认并保存", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "编辑", exact: true }),
  ).toBeVisible();
  const list = await (await page.request.get("/api/v1/materials/jobs")).json();
  expect(list.total).toBe(1);
  expect(list.items[0].version).toBe(2);
  const versions = await (
    await page.request.get(
      `/api/v1/materials/jobs/${list.items[0].id}/versions`,
    )
  ).json();
  expect(versions.items[0].snapshot.fields.requirements).toContain("MySQL");
  expect(versions.items[1].snapshot.fields.requirements).toContain("Redis");
  expect(versions.items[1].snapshot.fields.useInference).toBe(false);
  await mkdir("../artifacts/material-service", { recursive: true });
  await expect(page.locator(".jd-history-row .collapse-content")).toHaveCount(
    0,
  );
  await page.screenshot({
    path: "../artifacts/material-service/jd-history.png",
  });
});

test("旧页面保存冲突不覆盖新版本，其他账号不能访问原文件", async ({
  page,
  browser,
}) => {
  const user = await account();
  await login(page, user);
  await page.goto("/#/resumes");
  await upload(page);
  await page.getByRole("button", { name: "确认并保存", exact: true }).click();
  await expect(page.locator(".resume-record .ui-badge")).toHaveText("已确认");
  await page.getByRole("button", { name: "编辑", exact: true }).click();
  const list = await (
    await page.request.get("/api/v1/materials/resumes")
  ).json();
  const row = list.items[0];
  const snapshots = await (
    await page.request.get(`/api/v1/materials/resumes/${row.id}/versions`)
  ).json();
  const privateId = snapshots.items[0].snapshot.fileId;
  const staticAttempt = await page.request.get(
    `/@fs/${fileURLToPath(new URL("../../backend/data/materials/", import.meta.url)).replaceAll("\\", "/")}${privateId}`,
  );
  expect([403, 404]).toContain(staticAttempt.status());
  const headers = await csrf(page.request);
  const changed = await page.request.patch(
    `/api/v1/materials/resumes/${row.id}`,
    { headers, data: { revision: row.revision, title: "其他页面更新" } },
  );
  expect(changed.status()).toBe(200);
  await page.getByLabel("个人职责", { exact: true }).fill("旧页面未保存内容");
  await page.getByRole("button", { name: "确认并保存", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("材料已在其他页面更新");
  await expect(page.getByLabel("个人职责", { exact: true })).toHaveValue(
    "旧页面未保存内容",
  );
  const second = await browser.newContext();
  try {
    const other = await second.newPage();
    await login(other, await account());
    const file = await other.request.get(
      `/api/v1/materials/resumes/${row.id}/file`,
    );
    expect(file.status()).toBe(404);
    await other.goto("/#/resumes");
    await expect(other.locator(".resume-record")).toHaveCount(0);
  } finally {
    await second.close();
  }
});

test("损坏文件不入库，读取失败保留错误且不误报上传成功", async ({ page }) => {
  await login(page, await account());
  await page.goto("/#/resumes");
  await page.getByRole("button", { name: "上传简历", exact: true }).click();
  await page.getByLabel("选择简历文件").setInputFiles({
    name: "fake.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("not pdf"),
  });
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText(
    "文件内容与格式不符或已损坏",
  );
  await expect(page.locator(".resume-record")).toHaveCount(0);
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "取消", exact: true })
    .click();
  await page.route("**/api/v1/materials/resumes?*", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({
            error: {
              code: "DATABASE_UNAVAILABLE",
              message: "材料服务暂不可用",
            },
          }),
        })
      : route.continue(),
  );
  await page.reload();
  await expect(page.getByRole("alert")).toContainText("材料服务暂不可用");
});
