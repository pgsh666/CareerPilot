import { test, expect, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { signInPreview } from "./auth";

const key = "careerpilot:frontend:v2";
async function saved(page: Page) {
  return page.evaluate((key) => JSON.parse(localStorage.getItem(key)!), key);
}
async function go(page: Page, path: string) {
  await page.goto("/#" + path);
  await expect(page.locator(".entry-snapshot,.route-snapshot")).toHaveCount(0);
}
async function login(page: Page, admin = false) {
  await go(page, "/login?form=login");
  await page
    .getByLabel("邮箱", { exact: true })
    .fill(admin ? "admin@example.com" : "user@example.com");
  await page.getByLabel("密码", { exact: true }).fill("Pilot@2026");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/#\/home$/);
  await expect(page.locator(".entry-snapshot")).toHaveCount(0);
}
async function logout(page: Page, admin = false) {
  await go(page, admin ? "/admin" : "/settings");
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(page).toHaveURL(/#\/login\?form=login$/);
  await expect(page.locator(".entry-snapshot")).toHaveCount(0);
}
async function prepare(page: Page) {
  await go(page, "/interview?tab=prepare");
  await page.getByRole("button", { name: "3 道", exact: true }).click();
  await page
    .getByRole("checkbox", { name: "确认使用以上岗位信息和简历" })
    .check();
  await page.getByRole("button", { name: "进入面试", exact: true }).click();
  await expect(page.locator(".room-question")).toBeVisible();
}
async function replaceFile(page: Page, content: string) {
  await go(page, "/resumes");
  await page
    .locator('[data-record="failed"]')
    .getByRole("button", { name: "重新上传", exact: true })
    .click();
  await page.getByLabel("选择简历文件", { exact: true }).setInputFiles({
    name: "个人简历.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(content),
  });
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(page.locator(".resume-paper")).toHaveText(content);
  await page.getByRole("button", { name: "收起校对", exact: true }).click();
  await expect(
    page.locator('.collapse-region[data-expanding="true"]'),
  ).toHaveCount(0);
}
async function downloadedText(page: Page) {
  const row = page.locator('[data-record="failed"]');
  await row.locator(".resume-more-trigger").click();
  const downloading = page.waitForEvent("download");
  await page.getByRole("button", { name: "下载原文件", exact: true }).click();
  const download = await downloading;
  expect(download.suggestedFilename()).toBe("个人简历.txt");
  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream!) chunks.push(Buffer.from(chunk));
  return Buffer.concat(chunks).toString("utf8");
}

test("账号往返：资料、同ID材料原文件、JD草稿、会话和记录分别恢复", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await signInPreview(page);
  await go(page, "/settings");
  await page.getByLabel("用户名", { exact: true }).fill("审核用户");
  await page.getByRole("button", { name: "保存修改", exact: true }).click();
  await page.getByRole("button", { name: "更换头像", exact: true }).click();
  await page.getByRole("button", { name: "使用默认头像", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await replaceFile(page, "普通用户专属简历原文");
  const userFile = (await saved(page)).resumes.find(
    (r: any) => r.id === "failed",
  ).fileKey;
  await go(page, "/interview");
  await page.getByLabel("粘贴岗位JD原文").fill("普通用户尚未提交的 JD 草稿");
  await prepare(page);
  await page.getByLabel("回答文字").fill("普通用户的回答草稿");
  const user = await saved(page);
  // Entering login directly also saves the previous identity before switching.
  await login(page, true);
  let admin = await saved(page);
  expect(admin.account.role).toBe("admin");
  expect(admin.session).toBeNull();
  expect(admin.jobDraft).toBeNull();
  expect(admin.runs).toEqual([]);
  expect(admin.completedTasks).toEqual([]);
  expect(
    admin.resumes.find((r: any) => r.id === "failed").fileKey,
  ).toBeUndefined();
  await replaceFile(page, "管理员专属简历原文");
  const adminFile = (await saved(page)).resumes.find(
    (r: any) => r.id === "failed",
  ).fileKey;
  expect(adminFile).not.toBe(userFile);
  expect(await downloadedText(page)).toBe("管理员专属简历原文");
  await page.reload();
  expect(
    (await saved(page)).resumes.find((r: any) => r.id === "failed").fileKey,
  ).toBe(adminFile);
  await logout(page, true);
  await login(page);
  const restored = await saved(page);
  for (const field of [
    "account",
    "resumes",
    "jobs",
    "jobDraft",
    "session",
    "runs",
    "completedTasks",
  ])
    expect(restored[field], field).toEqual(user[field]);
  await expect(page.locator(".user-greeting")).toHaveText("您好，审核用户");
  await expect(page.locator('.user-avatar [data-icon="user"]')).toBeVisible();
  await page.getByRole("link", { name: "继续面试", exact: true }).click();
  await expect(page.getByLabel("回答文字")).toHaveValue("普通用户的回答草稿");
  await page.getByRole("button", { name: "结束面试", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await go(page, "/resumes");
  expect(await downloadedText(page)).toBe("普通用户专属简历原文");
  const runs = (await saved(page)).runs;
  expect(runs).toHaveLength(1);
  await logout(page);
  await page.reload();
  await login(page, true);
  expect((await saved(page)).runs).toEqual([]);
  await logout(page, true);
  await login(page);
  expect((await saved(page)).runs).toEqual(runs);
  expect((await saved(page)).session).toBeNull();
  await expect(page.locator('.user-avatar [data-icon="user"]')).toBeVisible();
});

test("旧版状态迁移：保留资料、材料、草稿、完成任务及全局管理员状态", async ({
  page,
}) => {
  test.setTimeout(60_000);
  await signInPreview(page);
  await prepare(page);
  await page.getByLabel("回答文字").fill("旧版保留的回答");
  const legacy = await saved(page);
  delete legacy.accounts;
  legacy.account.name = "旧版用户名";
  legacy.account.avatar = "leaf";
  legacy.resumes[0].title = "旧版材料";
  legacy.jobs[0].title = "旧版岗位";
  legacy.jobDraft = { ...legacy.jobs[0], source: "旧版JD草稿" };
  legacy.completedTasks = ["index"];
  legacy.adminUsers[0].enabled = false;
  await page.evaluate(
    ({ key, legacy }) => localStorage.setItem(key, JSON.stringify(legacy)),
    { key, legacy },
  );
  await page.reload();
  await expect(page.getByLabel("回答文字")).toHaveValue("旧版保留的回答");
  await login(page, true);
  expect((await saved(page)).adminUsers).toEqual(legacy.adminUsers);
  expect((await saved(page)).completedTasks).toEqual([]);
  await login(page);
  const restored = await saved(page);
  for (const field of [
    "account",
    "resumes",
    "jobs",
    "jobDraft",
    "session",
    "completedTasks",
    "adminUsers",
  ])
    expect(restored[field], field).toEqual(legacy[field]);
  await page.reload();
  await expect(page.locator(".user-greeting")).toHaveText("您好，旧版用户名");
});

test("简历保存：清空技能与项目会同步清空列表摘要，刷新后保持一致", async ({
  page,
}) => {
  await signInPreview(page);
  await go(page, "/resumes");
  const row = page.locator('[data-record="backend"]');
  await row.getByRole("button", { name: "校对简历", exact: true }).click();
  await page.getByRole("tab", { name: "项目经历", exact: true }).click();
  await page.getByLabel("项目名称", { exact: true }).fill("接口项目");
  await page.getByRole("tab", { name: "基本信息", exact: true }).click();
  await expect(page.locator(".tab-slide-snapshot")).toHaveCount(0);
  await page.getByLabel("姓名", { exact: true }).fill("林同学");
  await page.getByRole("tab", { name: "个人技能", exact: true }).click();
  await page
    .getByLabel("个人技能", { exact: true })
    .fill("审核技能， Python；MySQL\nGit");
  await page.getByRole("button", { name: "确认并保存", exact: true }).click();
  await expect(row.locator(".resume-summary")).toContainText("1 个项目");
  await expect(row.locator(".resume-skill")).toHaveText([
    "审核技能",
    "Python",
    "MySQL",
    "Git",
  ]);
  await row.getByRole("button", { name: "编辑", exact: true }).click();
  await page.getByRole("tab", { name: "项目经历", exact: true }).click();
  await page.getByLabel("项目名称", { exact: true }).fill("");
  await page.getByRole("tab", { name: "个人技能", exact: true }).click();
  await page.getByLabel("个人技能", { exact: true }).fill("  \n ");
  await page.getByRole("button", { name: "确认并保存", exact: true }).click();
  await page.reload();
  await expect(row.locator(".resume-summary")).toHaveText("0 个项目");
  await expect(row.locator(".resume-skill")).toHaveCount(0);
  const resume = (await saved(page)).resumes[0];
  expect(resume.projects).toBe(0);
  expect(resume.skills).toEqual([]);
  expect(resume.fields.name).toBe("林同学");
});

test("空白简历禁止确认，空格同样拦截；仅实习信息可正常保存", async ({
  page,
}) => {
  await signInPreview(page);
  await go(page, "/resumes");
  const before = (await saved(page)).resumes[0];
  await page.getByRole("button", { name: "校对简历", exact: true }).click();
  await page.getByRole("button", { name: "确认并保存", exact: true }).click();
  await expect(page.locator(".global-toast")).toHaveText(
    "请至少填写一项简历信息后再确认保存",
  );
  await expect(
    page.getByRole("button", { name: "收起校对", exact: true }),
  ).toBeVisible();
  expect((await saved(page)).resumes[0]).toEqual(before);
  await page.getByRole("tab", { name: "项目经历", exact: true }).click();
  await page.getByLabel("项目名称", { exact: true }).fill("   ");
  await page.getByRole("button", { name: "确认并保存", exact: true }).click();
  expect((await saved(page)).resumes[0]).toEqual(before);
  await page.getByRole("tab", { name: "实习经历", exact: true }).click();
  await page.getByLabel("公司名称", { exact: true }).fill("实习公司");
  await page.getByRole("button", { name: "确认并保存", exact: true }).click();
  await page.reload();
  const resume = (await saved(page)).resumes[0];
  expect(resume.status).toBe("confirmed");
  expect(resume.fields.internships[0].company).toBe("实习公司");
  expect(resume.projects).toBe(0);
  expect(resume.skills).toEqual([]);
});

test("首页：无会话从准备开始，有会话恢复真实进度及草稿，结束后恢复空态", async ({
  page,
}) => {
  test.setTimeout(45_000);
  await signInPreview(page);
  const action = page.locator(".continuation-card .card-action");
  await expect(action).toHaveText("开始新面试");
  await expect(action).toHaveAttribute("href", "#/interview?tab=prepare");
  await expect(
    page.getByRole("progressbar", { name: "面试进度" }),
  ).toHaveAttribute("aria-valuenow", "0");
  await action.click();
  await expect(page.locator(".interview-materials")).toBeVisible();
  await prepare(page);
  await page.getByRole("button", { name: "跳过本题", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(page.locator(".tab-slide-snapshot")).toHaveCount(0);
  await page.getByLabel("回答文字").fill("第二题尚未提交的回答");
  await go(page, "/home");
  await expect(page.locator(".continuation-card .progress-label")).toHaveText(
    "主问题 2 / 3",
  );
  await expect(
    page.getByRole("progressbar", { name: "面试进度" }),
  ).toHaveAttribute("aria-valuenow", "2");
  await expect(action).toHaveText("继续面试");
  await action.click();
  await expect(page.getByLabel("回答文字")).toHaveValue("第二题尚未提交的回答");
  await page.getByRole("button", { name: "结束面试", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await go(page, "/home");
  await expect(page.locator(".continuation-card .progress-label")).toHaveText(
    "暂无进行中的面试",
  );
  await expect(action).toHaveText("开始新面试");
  await mkdir("../artifacts/frontend-fixes-2026-10-24", { recursive: true });
  await page.screenshot({
    path: "../artifacts/frontend-fixes-2026-10-24/home-idle.png",
  });
});

test("首页：进行中的复练显示复练入口并恢复原题草稿", async ({ page }) => {
  await signInPreview(page);
  await go(page, "/interview?tab=tasks&task=index");
  await page.getByRole("button", { name: "开始复练", exact: true }).click();
  await page.getByLabel("回答文字").fill("我的复练草稿");
  await go(page, "/home");
  await expect(page.locator(".continuation-card .progress-label")).toHaveText(
    "原题复练进行中",
  );
  await expect(
    page.getByRole("progressbar", { name: "复练进度" }),
  ).toHaveAttribute("aria-valuenow", "0");
  await page.getByRole("link", { name: "继续复练", exact: true }).click();
  await expect(page.getByLabel("回答文字")).toHaveValue("我的复练草稿");
});

test("简历更多菜单：外部点击、Esc恢复焦点、互斥切换和离开清理", async ({
  page,
}) => {
  await signInPreview(page);
  await go(page, "/resumes");
  const triggers = page.locator(".resume-more-trigger");
  const first = triggers.first();
  await first.click();
  await expect(first).toHaveAttribute("aria-expanded", "true");
  await page.getByRole("heading", { name: "我的简历", exact: true }).click();
  await expect(page.locator(".resume-menu")).toHaveCount(0);
  await first.focus();
  await page.keyboard.press("Enter");
  await page.getByRole("button", { name: "重命名", exact: true }).focus();
  await page.keyboard.press("Escape");
  await expect(first).toBeFocused();
  await expect(first).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator(".resume-menu")).toHaveCount(0);
  await first.click();
  await triggers.nth(1).click();
  await expect(first).toHaveAttribute("aria-expanded", "false");
  await expect(triggers.nth(1)).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator(".resume-menu:not([inert])")).toHaveCount(1);
  await page.getByRole("button", { name: "重命名", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await first.click();
  await page.getByRole("button", { name: "上传简历", exact: true }).click();
  await expect(page.locator(".resume-menu")).toHaveCount(0);
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await first.click();
  await page
    .getByRole("navigation", { name: "主导航" })
    .getByRole("link", { name: "设置", exact: true })
    .click();
  await expect(page.locator(".route-snapshot")).toHaveCount(0);
  await page.getByRole("button", { name: "更换头像", exact: true }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});


