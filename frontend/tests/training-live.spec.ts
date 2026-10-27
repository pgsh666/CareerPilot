import { fileURLToPath } from "node:url";
import { test, expect, type Page } from "@playwright/test";
import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";

interface User {
  id: string;
  email: string;
  password: string;
}
let emails: string[] = [];
const source =
  "姓名：统一联调\n学校：测试大学\n项目名称：材料服务\n个人职责：维护上传接口\n项目内容：实现访问控制\n专业技能：Python、MySQL";
const jd =
  "岗位名称：后端开发工程师\n岗位方向：Python\n岗位职责：开发接口\n任职要求：熟悉Python与MySQL";
function fixture<T = unknown>(body: Record<string, unknown>): Promise<T> {
  return new Promise((resolve, reject) => {
    const child = execFile(
      (process.env.CAREERPILOT_PYTHON || "python"),
      [fileURLToPath(new URL("../../backend/scripts/auth_browser_fixture.py", import.meta.url))],
      { windowsHide: true, timeout: 15000 },
      (err, stdout) => {
        if (err) reject(new Error("临时测试账号操作失败"));
        else {
          try {
            resolve(JSON.parse(stdout));
          } catch {
            reject(new Error("测试辅助程序响应异常"));
          }
        }
      },
    );
    child.stdin?.end(JSON.stringify(body));
  });
}
async function account(role = "user") {
  const email = `browser-auth-${randomUUID().replaceAll("-", "")}-a@example.org`;
  emails.push(email);
  return fixture<User>({ action: "prepare", email, role });
}
async function login(page: Page, user: User) {
  await page.goto("/#/login?form=login");
  await page.getByLabel("邮箱", { exact: true }).fill(user.email);
  await page.getByLabel("密码", { exact: true }).fill(user.password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/#\/home$/);
  await expect(page.locator(".entry-snapshot")).toHaveCount(0);
}
async function materials(page: Page) {
  await page.goto("/#/resumes");
  await page.getByRole("button", { name: "上传简历", exact: true }).click();
  await page
    .getByLabel("选择简历文件")
    .setInputFiles({
      name: "真实流程测试.txt",
      mimeType: "text/plain",
      buffer: Buffer.from(source),
    });
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0, { timeout: 15000 });
  await page.getByRole("button", { name: "确认并保存", exact: true }).click();
  await expect(page.locator(".resume-record .ui-badge")).toHaveText("已确认");
  await page.goto("/#/interview");
  await page.getByLabel("粘贴岗位JD原文").fill(jd);
  await page.getByRole("button", { name: "解析 JD", exact: true }).click();
  await expect(page.getByLabel("岗位名称", { exact: true })).toHaveValue(
    "后端开发工程师",
  );
  await page.getByRole("button", { name: "确认并保存", exact: true }).click();
  await page.getByRole("tab", { name: "模拟面试", exact: true }).click();
}
async function begin(page: Page) {
  await materials(page);
  await page.locator(".question-count button").first().click();
  await page.getByLabel("确认使用以上岗位信息和简历").check();
  await page.getByRole("button", { name: "进入面试", exact: true }).click();
  await expect(page).toHaveURL(/#\/interview\/room\?id=/);
  await expect(page.locator(".room-panel > .tab-slide-viewport > .tab-slide-pane .room-question p")).toContainText("第1题");
}
async function voiceAnswer(page: Page) {
  await page.getByRole("button", { name: "开始录音", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "结束录音", exact: true }),
  ).toBeVisible();
  await page.waitForTimeout(1200);
  await page.getByRole("button", { name: "结束录音", exact: true }).click();
}
test.beforeEach(() => {
  emails = [];
});
test.afterEach(async () => {
  if (emails.length) await fixture({ action: "cleanup", emails });
});

test("三题正式语音自动提交、证据报告、两阶段可编辑复练及历史真实统计", async ({
  page,
}) => {
  await login(page, await account());
  await begin(page);
  await expect(page.locator(".room-panel > .tab-slide-viewport > .tab-slide-pane").getByLabel("回答文字")).toHaveJSProperty("readOnly", true);
  await expect(
    page.getByRole("button", { name: "提交回答", exact: true }),
  ).toHaveCount(0);
  await voiceAnswer(page);
  await expect(page.locator(".room-panel > .tab-slide-viewport > .tab-slide-pane .room-question p")).toContainText("第2题");
  await voiceAnswer(page);
  await expect(page.locator(".room-panel > .tab-slide-viewport > .tab-slide-pane .room-question p")).toContainText("第3题");
  await voiceAnswer(page);
  await expect(page).toHaveURL(/#\/reports\//);
  await expect(page.locator(".priority-card")).toHaveCount(1, {
    timeout: 15000,
  });
  await expect(page.locator(".route-snapshot")).toHaveCount(0);
  await expect
    .poll(() =>
      page
        .locator(".route-viewport > .business-page")
        .evaluate((e) => Math.round(e.getBoundingClientRect().right)),
    )
    .toBeLessThanOrEqual(1440);
  await page.screenshot({
    path: "../artifacts/training-service/report.png",
    fullPage: true,
  });
  const reportURL = page.url();
  await page.getByRole("tab", { name: "逐题回顾", exact: true }).click();
  await expect(page.locator(".actual-answer").first()).toContainText(
    "本地语音替身文本",
  );
  await page.getByRole("tab", { name: "维度评分", exact: true }).click();
  await expect(page.locator(".result-dimensions")).toContainText(
    "careerpilot-rubric-v1",
  );
  await page.getByRole("tab", { name: "报告概览", exact: true }).click();
  await page.getByRole("link", { name: "去复练", exact: true }).click();
  await expect(page.locator(".practice-task.selected")).toHaveCount(1);
  await page.getByRole("button", { name: "开始复练", exact: true }).click();
  await expect(page).toHaveURL(/#\/interview\/room/);
  await expect(page.locator(".room-panel > .tab-slide-viewport > .tab-slide-pane").getByLabel("回答文字")).toHaveJSProperty("readOnly", false);
  await voiceAnswer(page);
  await expect(page.locator(".room-panel > .tab-slide-viewport > .tab-slide-pane").getByLabel("回答文字")).toContainText("");
  await expect(page.locator(".room-panel > .tab-slide-viewport > .tab-slide-pane").getByLabel("回答文字")).toHaveValue(/本地语音替身文本/);
  await page
    .getByLabel("回答文字")
    .fill("复练修改后的原题回答：我增加了访问控制与验证依据。");
  await page.getByRole("button", { name: "提交回答", exact: true }).click();
  await expect(page.locator(".room-feedback")).toContainText("原题重答反馈");
  await page.getByRole("button", { name: "进入变式练习", exact: true }).click();
  await expect(page.locator(".room-panel > .tab-slide-viewport > .tab-slide-pane .room-question p")).toContainText("请求突然增多");
  await page
    .getByLabel("回答文字")
    .fill("变式回答：分层检查令牌、资源归属，再运行并发权限验证。");
  await page.getByRole("button", { name: "提交回答", exact: true }).click();
  await expect(page).toHaveURL(/#\/practice\//);
  await expect(page.locator(".source-original")).toContainText(
    "本地语音替身文本",
  );
  await expect(page.locator(".source-original")).not.toContainText(
    "复练修改后的",
  );
  await expect(page.locator(".result-panel > .tab-slide-viewport > .tab-slide-pane .practice-detail")).toContainText(
    "复练修改后的原题回答",
  );
  await page.getByRole("tab", { name: "变式验证", exact: true }).click();
  await expect(page.locator(".result-panel > .tab-slide-viewport > .tab-slide-pane .practice-detail")).toContainText("分层检查令牌");
  await page.goto("/#/history");
  await expect(page.locator(".history-rows .data-row")).toHaveCount(1);
  await expect(page.locator(".history-score")).toHaveText("75");
  await expect(page.locator('.trend-chart svg')).toBeVisible();
  await page.getByRole("tab", { name: /薄弱项复练/ }).click();
  await expect(page.locator(".history-rows .data-row")).toContainText("已完成");
  await page.goto("/#/home");
  await expect(page.locator(".recap-card")).toContainText("1");
  await page.goto(reportURL);
  await page.getByRole("tab", { name: "逐题回顾" }).click();
  await expect(page.locator(".actual-answer").first()).not.toContainText(
    "复练修改后的",
  );
});

test("麦克风故障开放键盘、退出续做保留草稿和题目、跳过及提前结束", async ({
  page,
  context,
}) => {
  const user = await account();
  await context.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = async () => {
      throw new DOMException("denied", "NotAllowedError");
    };
  });
  await login(page, user);
  await begin(page);
  const roomURL = page.url(),
    question = await page.locator(".room-panel > .tab-slide-viewport > .tab-slide-pane .room-question p").innerText();
  await page.getByRole("button", { name: "开始录音", exact: true }).click();
  await expect(page.locator(".room-panel > .tab-slide-viewport > .tab-slide-pane").getByLabel("回答文字")).toHaveJSProperty("readOnly", false);
  await page.locator(".room-panel > .tab-slide-viewport > .tab-slide-pane").getByLabel("回答文字").fill("尚未提交的键盘故障草稿");
  await page.reload();
  await expect(page.locator(".room-panel > .tab-slide-viewport > .tab-slide-pane").getByLabel("回答文字")).toHaveValue(
    "尚未提交的键盘故障草稿",
  );
  await page.goto("/#/settings");
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await login(page, user);
  await page.getByRole("link", { name: "继续面试", exact: true }).click();
  await expect(page).toHaveURL(roomURL);
  await expect(page.locator(".room-panel > .tab-slide-viewport > .tab-slide-pane .room-question p")).toHaveText(question);
  await expect(page.locator(".room-panel > .tab-slide-viewport > .tab-slide-pane").getByLabel("回答文字")).toHaveValue(
    "尚未提交的键盘故障草稿",
  );
  await page.getByRole("button", { name: "跳过本题", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(page.locator(".room-panel > .tab-slide-viewport > .tab-slide-pane .room-question p")).toContainText("第2题");
  await page.getByRole("button", { name: "结束面试", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(page).toHaveURL(/#\/reports\//);
  await expect(page.locator(".report-summary")).toContainText(
    "尚未提交有效回答",
  );
});

test("永久注销、真实管理概况和只读费用明细", async ({ page }) => {
  const user = await account(),
    admin = await account("admin");
  await login(page, user);
  await page.goto("/#/settings");
  await page.getByRole("button", { name: "注销账号", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("个人数据保留30天");
  await page.getByLabel("确认账号邮箱").fill(user.email);
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(page).toHaveURL(/#\/login/);
  await login(page, admin);
  await page.goto("/#/admin");
  await page.getByLabel("搜索用户名或邮箱").fill(user.email);
  await expect(page.locator(".admin-user-rows .ui-badge")).toHaveText("已注销");
  await expect(
    page.getByRole("button", { name: "启用", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("tab", { name: "运行概况", exact: true }).click();
  await expect(page.locator(".service-line").first()).toContainText("正常");
  await page.getByRole("tab", { name: "模型用量", exact: true }).click();
  await expect(page.locator(".budget-summary")).toContainText("50");
  const actualUsage = await (await page.request.get('/api/v1/admin/usage?limit=4')).json();
  await expect(page.locator(".usage-table")).toContainText(actualUsage.items[0]?.purposeLabel || '暂无');
  await expect(page.locator(".budget-note")).toContainText("20");
});

test("另一标签页只读，显式接管后旧页不能作答", async ({ page, context }) => {
  await login(page, await account());
  await begin(page);
  const other = await context.newPage();
  await other.goto(page.url());
  await expect(other.getByRole('button', { name: '接管作答', exact: true })).toBeVisible();
  await expect(other.getByRole('button', { name: '开始录音', exact: true })).toBeDisabled();
  await other.getByRole('button', { name: '接管作答', exact: true }).click();
  await other.getByRole('dialog').getByRole('button', { name: '确认', exact: true }).click();
  await expect(other.getByRole('button', { name: '开始录音', exact: true })).toBeEnabled();
  await page.bringToFront();
  await expect(page.getByRole('button', { name: '接管作答', exact: true })).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole('button', { name: '开始录音', exact: true })).toBeDisabled();
  await other.close();
});

test("首次转写故障可在当前页手动重试一次，成功后自动提交原文", async ({ page }) => {
  await login(page, await account());
  await begin(page);
  let failed = false;
  await page.route('**/training/sessions/*/transcripts?*', async route => {
    if (!failed) {
      failed = true;
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'ASR_UNAVAILABLE', message: '本地故障注入' } }) });
    } else await route.continue();
  });
  await voiceAnswer(page);
  await expect(page.getByRole('button', { name: '重试转写一次', exact: true })).toBeVisible();
  await expect(page.locator('.room-question p')).toContainText('第1题');
  await page.getByRole('button', { name: '重试转写一次', exact: true }).click();
  await expect(page.locator('.room-panel > .tab-slide-viewport > .tab-slide-pane .room-question p')).toContainText('第2题');
  await expect(page.getByRole('button', { name: '重试转写一次', exact: true })).toHaveCount(0);
});
