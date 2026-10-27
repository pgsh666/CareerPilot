import { test, expect, type Page } from "@playwright/test";
import { readFile, mkdir } from "node:fs/promises";
import { createHash } from "node:crypto";
import { resolve } from "node:path";
const storageKey = "careerpilot:frontend:v2";
import { signInPreview } from "./auth";
async function go(page: Page, path: string) {
  await page.goto("/#" + path);
  await expect(page.locator(".route-snapshot")).toHaveCount(0);
}
async function prepare(page: Page, count = 3) {
  await go(page, "/interview?tab=prepare");
  await page
    .getByRole("button", { name: `${count} 道`, exact: count !== 5 })
    .click();
  await page
    .getByRole("checkbox", { name: "确认使用以上岗位信息和简历" })
    .check();
  await page.getByRole("button", { name: "进入面试", exact: true }).click();
  await expect(page.locator(".room-question")).toBeVisible();
}
async function adminLogin(page: Page) {
  await go(page, "/login?form=login");
  await page.getByLabel("邮箱", { exact: true }).fill("admin@example.com");
  await page.getByLabel("密码", { exact: true }).fill("Pilot@2026");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page
    .getByRole("navigation", { name: "主导航" })
    .getByRole("link", { name: "设置", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "管理中心", exact: true }),
  ).toBeVisible();
}
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    if ("speechSynthesis" in window) {
      window.speechSynthesis.speak = () => {};
      window.speechSynthesis.cancel = () => {};
    }
  });
  await signInPreview(page);
});

test("简历：五类空白字段、取消草稿、保存、TXT上传及更多操作", async ({
  page,
}) => {
  await go(page, "/resumes");
  await page.getByRole("button", { name: "校对简历", exact: true }).click();
  await expect(page.locator(".resume-paper")).toHaveText("");
  await expect(page.getByRole("tab")).toHaveText([
    "基本信息",
    "教育经历",
    "实习经历",
    "项目经历",
    "个人技能",
  ]);
  await expect(page.getByRole("tab", { name: "基本信息", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "项目经历", exact: true }).click();
  await page.getByLabel("项目名称", { exact: true }).fill("接口项目");
  await page.getByRole("button", { name: "收起校对", exact: true }).click();
  await page.getByRole("button", { name: "校对简历", exact: true }).click();
  await expect(page.getByRole("tab", { name: "基本信息", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "项目经历", exact: true }).click();
  await expect(page.getByLabel("项目名称", { exact: true })).toHaveValue("");
  await page.getByLabel("项目名称", { exact: true }).fill("接口项目");
  await page.getByRole("tab", { name: "实习经历", exact: true }).click();
  await page.getByLabel("公司名称", { exact: true }).fill("测试公司");
  await page.getByRole("tab", { name: "项目经历", exact: true }).click();
  await expect(
    page.getByRole("textbox", { name: "项目名称", exact: true }),
  ).toHaveValue("接口项目");
  await page.getByRole("button", { name: "确认并保存", exact: true }).click();
  await page.reload();
  await expect(
    page
      .locator(".resume-record")
      .first()
      .getByRole("button", { name: "编辑", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "上传简历", exact: true }).click();
  await page.getByLabel("选择简历文件", { exact: true }).setInputFiles({
    name: "我的简历.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("原始简历内容\n接口与数据库项目", "utf8"),
  });
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(page.locator(".resume-paper")).toContainText("原始简历内容");
  await expect(page.getByRole("tab", { name: "基本信息", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("button", { name: "收起校对", exact: true }).click();
  await page
    .getByRole("button", { name: "我的简历的更多操作", exact: true })
    .click();
  await page.getByRole("button", { name: "重命名", exact: true }).click();
  await page.getByLabel("简历名称", { exact: true }).fill("新名称");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "新名称", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "新名称的更多操作", exact: true })
    .click();
  await page.getByRole("button", { name: "下载原文件", exact: true }).click();
  await page
    .getByRole("button", { name: "新名称的更多操作", exact: true })
    .click();
  await page.getByRole("button", { name: "删除简历", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "删除", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "新名称", exact: true }),
  ).toHaveCount(0);
});

test("JD：原文空值、手动校对、持久化历史、修改失效与同一记录不重复新增", async ({
  page,
}) => {
  await go(page, "/interview");
  await expect(
    page.getByRole("button", { name: "解析 JD", exact: true }),
  ).toBeDisabled();
  await page
    .getByLabel("粘贴岗位JD原文")
    .fill("测试岗位\n岗位要求：了解 Python 和数据库。");
  await page.getByRole("button", { name: "解析 JD", exact: true }).click();
  await page.getByLabel("岗位名称", { exact: true }).fill("测试后端岗位");
  await page.getByLabel("公司名称", { exact: true }).fill("测试公司");
  await page.getByLabel("岗位类别", { exact: true }).selectOption("后端开发");
  await page.getByLabel("岗位方向", { exact: true }).fill("Python 后端");
  await page
    .getByLabel("明确要求", { exact: true })
    .fill("了解 Python 和数据库");
  await page.getByRole("button", { name: "确认并保存", exact: true }).click();
  await page.reload();
  await expect(page.getByLabel("岗位名称", { exact: true })).toHaveValue(
    "测试后端岗位",
  );
  await page.getByRole("button", { name: "历史 JD（4）", exact: true }).click();
  await expect(page.locator(".jd-history-row")).toHaveCount(3);
  await page
    .locator(".jd-history-row")
    .first()
    .getByRole("button", { name: "编辑", exact: true })
    .click();
  await page.getByLabel("粘贴岗位JD原文").fill("更新后的原文");
  await expect(
    page.getByRole("button", { name: "确认并保存", exact: true }),
  ).toBeDisabled();
  await expect(page.getByLabel("岗位名称", { exact: true })).toHaveValue("");
  await page.getByRole("button", { name: "解析 JD", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "收起校对", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".jd-history-row")).toHaveCount(3);
});

test("模拟面试：材料门槛、两次追问、草稿刷新恢复、真实回答进入独立报告", async ({
  page,
}) => {
  await go(page, "/interview?tab=prepare");
  await expect(
    page.getByRole("button", { name: "进入面试", exact: true }),
  ).toBeDisabled();
  await prepare(page);
  await page.getByLabel("回答文字").fill("这是我的实际回答");
  await page.reload();
  await expect(page.getByLabel("回答文字")).toHaveValue("这是我的实际回答");
  await page.getByRole("button", { name: "提交回答", exact: true }).click();
  await expect(page.locator(".tab-slide-snapshot")).toHaveCount(0);
  await expect(page.locator(".room-top")).toContainText("追问 1 / 2");
  await page.getByLabel("回答文字").fill("第一次追问的回答");
  await page.getByRole("button", { name: "提交回答", exact: true }).click();
  await expect(page.locator(".tab-slide-snapshot")).toHaveCount(0);
  await expect(page.locator(".room-top")).toContainText("追问 2 / 2");
  await page.getByLabel("回答文字").fill("第二次追问的回答");
  await page.getByRole("button", { name: "提交回答", exact: true }).click();
  await expect(page.locator(".tab-slide-snapshot")).toHaveCount(0);
  await expect(page.locator(".room-top")).toContainText("第 2 题");
  await page.getByRole("button", { name: "结束面试", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(page).toHaveURL(/#\/reports\/interview-/);
  await expect(page.locator(".result-meta")).toContainText("提前结束");
  await expect(page.locator(".result-metric.score")).toContainText("—");
  await page.getByRole("tab", { name: "逐题回顾", exact: true }).click();
  await expect(page.locator(".original-answer")).toHaveText("这是我的实际回答");
  await page.locator("details").click();
  await expect(page.locator(".followups")).toContainText("第一次追问的回答");
  await expect(page.locator(".question-feedback")).toContainText("反馈待生成");
  await page.getByRole("link", { name: "返回历史", exact: true }).click();
  await expect(page.locator(".history-row-title").first()).toContainText(
    "本次练习记录",
  );
  await expect(page.locator(".chart-meta")).toContainText("1 场可比面试");
});

test("复练：原题与变式完成后才标记完成，详情与历史保留本次文字", async ({
  page,
}) => {
  await go(page, "/interview?tab=tasks&task=idempotency");
  await page.getByRole("button", { name: "开始复练", exact: true }).click();
  await page.getByLabel("回答文字").fill("本次原题重答");
  await page.getByRole("button", { name: "提交回答", exact: true }).click();
  await expect(page.locator(".room-feedback")).toContainText("本次原题重答");
  await page.getByRole("button", { name: "进入变式练习", exact: true }).click();
  await page.getByLabel("回答文字").fill("本次变式回答");
  await page.getByRole("button", { name: "提交回答", exact: true }).click();
  await page.getByRole("button", { name: "查看复练详情", exact: true }).click();
  await expect(page.locator(".answer-comparison .after")).toContainText(
    "本次原题重答",
  );
  await expect(page.locator(".result-stages")).toContainText("变式验证");
  await page.getByRole("tab", { name: "变式验证", exact: true }).click();
  await expect(page.locator(".original-answer")).toContainText("本次变式回答");
  await expect(page.locator(".variant-feedback")).toContainText("反馈待生成");
  await go(page, "/interview?tab=tasks");
  await expect(page.locator(".practice-task")).toHaveCount(2);
});

test("未完成复练从详情继续，保留原题并更新同一条本地记录", async ({ page }) => {
  await go(page, "/interview?tab=tasks&task=recovery");
  await page.getByRole("button", { name: "开始复练", exact: true }).click();
  await page.getByLabel("回答文字").fill("未完成记录的原题");
  await page.getByRole("button", { name: "提交回答", exact: true }).click();
  await page.getByRole("button", { name: "结束复练", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  const id = page.url().split("/practice/")[1];
  await page.getByRole("button", { name: "继续变式练习", exact: true }).click();
  await page.getByLabel("回答文字").fill("续做的变式");
  await page.getByRole("button", { name: "提交回答", exact: true }).click();
  await page.getByRole("button", { name: "查看复练详情", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(id + "$"));
  await expect(page.locator(".answer-comparison .after")).toContainText(
    "未完成记录的原题",
  );
  const runs = await page.evaluate(
    (key) => JSON.parse(localStorage.getItem(key)!).runs,
    storageKey,
  );
  expect(runs).toHaveLength(1);
  expect(runs[0].variant).toBe(true);
});

test("历史与结果：筛选隔离趋势、单样本和空态、详情来源一致与N/A", async ({
  page,
}) => {
  await go(page, "/history");
  await expect(page.locator(".chart-meta")).toContainText("6 场可比面试");
  await page.getByRole("tab", { name: /薄弱项复练/ }).click();
  await expect(page.locator(".chart-meta")).toContainText("6 场可比面试");
  await expect(page.locator(".history-rows .data-row")).toHaveCount(3);
  await page.getByLabel("目标岗位与JD版本").selectOption("booking-v1");
  await expect(page.locator(".chart-meta")).toContainText("1 场可比面试");
  await expect(page.locator(".trend-chart polyline")).toHaveCount(0);
  await page.getByLabel("岗位", { exact: true }).selectOption("frontend");
  await expect(page.locator(".trend-chart")).toContainText("暂无可比较");
  await go(page, "/reports/interview-7");
  await page.getByRole("tab", { name: "维度评分", exact: true }).click();
  await expect(page.locator(".dimension-grid")).toContainText("N/A");
  await page.getByRole("tab", { name: "逐题回顾", exact: true }).click();
  await page.locator(".question-list button").nth(2).click();
  await expect(page.locator(".review-body")).toContainText("本题未作答");
  await expect(page.locator(".original-answer")).toHaveCount(0);
  await go(page, "/practice/practice-3");
  const original = await page
    .locator(".answer-comparison article")
    .first()
    .locator("p")
    .textContent();
  await page.getByRole("link", { name: /来源：/ }).click();
  await expect(page.locator(".original-answer")).toHaveText(original!);
  await go(page, "/reports/unknown");
  await expect(
    page.getByRole("heading", { name: "该记录暂无详情" }),
  ).toBeVisible();
});

test("设置：不自动弹窗、头像与名称同步、密码校验、退出后受保护路由", async ({
  page,
}) => {
  await go(page, "/settings");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByLabel("用户名", { exact: true }).fill("新名字");
  await page.getByRole("button", { name: "保存修改", exact: true }).click();
  await expect(page.locator(".user-greeting")).toContainText("新名字");
  await page.getByRole("button", { name: "更换头像", exact: true }).click();
  await page.getByRole("button", { name: "使用默认头像", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await page.reload();
  await expect(page.locator('.profile-picture [data-icon="user"]')).toBeVisible();
  await expect(page.locator('.user-avatar [data-icon="user"]')).toBeVisible();
  await page.getByRole("button", { name: "修改密码", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(page.locator(".ui-modal .inline-error")).toHaveText(
    "请输入当前密码",
  );
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(page).toHaveURL(/#\/login/);
  await go(page, "/resumes");
  await expect(page).toHaveURL(/#\/login/);
});

test("登录：B立体翻转、密码显隐、错误提示、注册找回入口与管理员权限", async ({
  page,
}) => {
  await go(page, "/admin");
  await expect(page).toHaveURL(/#\/settings/);
  await go(page, "/login");
  await expect(page.locator(".auth-scene")).toHaveAttribute("inert", "");
  await page
    .getByRole("button", { name: "点击 CareerPilot 标志进入登录", exact: true })
    .click();
  await expect(page.locator(".auth-page")).toHaveAttribute(
    "data-state",
    "login",
  );
  await page.getByLabel("邮箱", { exact: true }).fill("bad");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.locator(".form-error")).toContainText("有效的邮箱");
  await page.getByLabel("密码", { exact: true }).fill("a");
  await page.getByRole("button", { name: "显示密码", exact: true }).click();
  await expect(page.getByLabel("密码", { exact: true })).toHaveAttribute(
    "type",
    "text",
  );
  await page.getByRole("button", { name: "立即注册", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "注册", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "返回登录", exact: true }).click();
  await page.getByRole("button", { name: "忘记密码？", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "找回密码", exact: true }),
  ).toBeVisible();
  await adminLogin(page);
  await expect(page.locator(".user-greeting")).toHaveText("管理员");
  await expect(
    page.getByRole("navigation", { name: "主导航" }).getByRole("link").last(),
  ).toHaveText("设置");
});

test("管理中心：筛选分页、启停确认、固定管理员和模型费用明细", async ({
  page,
}) => {
  await adminLogin(page);
  await expect(page.locator(".admin-stats article")).toHaveCount(4);
  await expect(page.locator(".admin-stats article p")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "退出登录", exact: true }),
  ).toBeVisible();
  await page.getByLabel("搜索用户名或邮箱").fill("zhou");
  await expect(page.locator(".admin-user-rows .data-row")).toHaveCount(1);
  await page.getByRole("button", { name: "启用", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "取消", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "启用", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "启用", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "停用", exact: true }),
  ).toBeVisible();
  await page.getByLabel("搜索用户名或邮箱").fill("admin@example.com");
  await expect(page.locator(".admin-user-rows")).toContainText("当前账号");
  await expect(
    page.getByRole("button", { name: "停用", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("tab", { name: "运行概况", exact: true }).click();
  await page.getByLabel("任务状态").selectOption("failed");
  await page.getByRole("button", { name: "查看详情", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("CP-202610");
  await expect(page.getByRole("dialog")).toContainText("返回字段不完整");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "关闭", exact: true })
    .click();
  await page.getByRole("tab", { name: "模型用量", exact: true }).click();
  await expect(page.locator(".budget-number")).toContainText("12.60");
  await expect(page.locator(".budget-remaining")).toContainText("37.40");
  await page.getByLabel("模型调用用途").selectOption("复练反馈");
  await expect(page.locator(".admin-call-details .list-footer")).toContainText(
    "8 次调用",
  );
  const exit = page.getByRole("button", { name: "退出登录", exact: true });
  for (const viewport of [
    { width: 1024, height: 768 },
    { width: 1440, height: 900 },
    { width: 2560, height: 1440 },
  ]) {
    await page.setViewportSize(viewport);
    const button = (await exit.boundingBox())!;
    const title = (await page
      .getByRole("heading", { name: "管理中心", exact: true })
      .boundingBox())!;
    expect(button.x).toBeGreaterThan(title.x + title.width);
    expect(button.x + button.width).toBeLessThan(viewport.width);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - innerWidth,
      ),
    ).toBe(0);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await mkdir("../artifacts/admin-logout", { recursive: true });
  await page.screenshot({
    path: "../artifacts/admin-logout/management-center.png",
  });
  const accounts = await page.evaluate(
    () =>
      JSON.parse(localStorage.getItem("careerpilot:frontend:v2")!).adminUsers,
  );
  await exit.click();
  const logout = page.getByRole("dialog", { name: "退出登录", exact: true });
  await expect(logout).toContainText("确认退出当前账号？");
  await expect(logout).not.toContainText("任务编号");
  await logout.getByRole("button", { name: "取消", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page).toHaveURL(/#\/admin$/);
  expect(
    await page.evaluate(
      () =>
        JSON.parse(localStorage.getItem("careerpilot:frontend:v2")!).signedIn,
    ),
  ).toBe(true);
  await exit.click();
  await logout.getByRole("button", { name: "确认", exact: true }).click();
  await expect(page).toHaveURL(/#\/login\?form=login$/);
  await expect(page.locator(".entry-snapshot")).toHaveCount(0);
  const saved = await page.evaluate(() =>
    JSON.parse(localStorage.getItem("careerpilot:frontend:v2")!),
  );
  expect(saved.signedIn).toBe(false);
  expect(saved.session).toBeNull();
  expect(saved.adminUsers).toEqual(accounts);
  await page.goBack();
  await expect(page).toHaveURL(/#\/login/);
  await go(page, "/admin");
  await expect(page).toHaveURL(/#\/login/);
  await expect(
    page.getByRole("heading", { name: "管理中心", exact: true }),
  ).toHaveCount(0);
});



test("语音状态：转写可编辑，权限失败保留草稿，离开页面释放识别", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const holder = window as unknown as {
      speechDenied: boolean;
      abortCount: number;
      SpeechRecognition?: unknown;
      webkitSpeechRecognition: unknown;
    };
    holder.speechDenied = false;
    holder.abortCount = 0;
    class Recognition {
      lang = "";
      continuous = false;
      interimResults = false;
      onstart: (() => void) | null = null;
      onend: (() => void) | null = null;
      onresult: ((event: unknown) => void) | null = null;
      onerror: ((event: { error: string }) => void) | null = null;
      start() {
        if (holder.speechDenied) {
          this.onerror?.({ error: "not-allowed" });
          this.onend?.();
        } else this.onstart?.();
      }
      stop() {
        setTimeout(() => {
          this.onresult?.({
            resultIndex: 0,
            results: [
              { isFinal: true, 0: { transcript: "语音识别的测试回答" } },
            ],
          });
          this.onend?.();
        }, 200);
      }
      abort() {
        holder.abortCount++;
        this.onend?.();
      }
    }
    Object.defineProperty(window, "SpeechRecognition", {
      configurable: true,
      value: Recognition,
    });
    Object.defineProperty(window, "webkitSpeechRecognition", {
      configurable: true,
      value: Recognition,
    });
  });
  await page.reload();
  await prepare(page);
  await page.getByRole("button", { name: "开始录音", exact: true }).click();
  await expect(page.getByLabel("回答文字")).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "提交回答", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "重播问题", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "结束录音", exact: true }).click();
  await expect(page.getByLabel("回答文字")).toHaveValue("语音识别的测试回答");
  await page.getByLabel("回答文字").fill("用户修正后的回答");
  await page.evaluate(() => {
    (window as unknown as { speechDenied: boolean }).speechDenied = true;
  });
  await page.getByRole("button", { name: "重新录音", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(page.locator(".room-error")).toContainText("未获得麦克风权限");
  await expect(page.getByLabel("回答文字")).toHaveValue("用户修正后的回答");
  await page.getByRole("button", { name: "提交回答", exact: true }).click();
  await page.evaluate(() => {
    (window as unknown as { speechDenied: boolean }).speechDenied = false;
  });
  await page.getByRole("button", { name: "开始录音", exact: true }).click();
  await page
    .getByRole("navigation", { name: "主导航" })
    .getByRole("link", { name: "首页", exact: true })
    .click();
  expect(
    await page.evaluate(
      () => (window as unknown as { abortCount: number }).abortCount,
    ),
  ).toBeGreaterThan(0);
});

test("跳过未作答的复练不会伪造已提交状态，可继续原题", async ({ page }) => {
  await go(page, "/interview?tab=tasks&task=index");
  await page.getByRole("button", { name: "开始复练", exact: true }).click();
  await page.getByRole("button", { name: "跳过本题", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认", exact: true })
    .click();
  await expect(page.locator(".answer-comparison .after")).toContainText(
    "未作答",
  );
  await expect(page.locator(".result-stages .done")).toHaveCount(0);
  await page.getByRole("button", { name: "继续原题练习", exact: true }).click();
  await expect(page.locator(".room-top")).toContainText("原题复练");
});

for (const viewport of [
  { width: 1024, height: 768 },
  { width: 1366, height: 768 },
  { width: 1920, height: 1080 },
  { width: 2560, height: 1440 },
]) {
  test(`全页面桌面布局 ${viewport.width}x${viewport.height}`, async ({
    page,
  }) => {
    test.setTimeout(90000);
    await page.setViewportSize(viewport);
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    const folder = resolve(
      `../artifacts/frontend-full/${viewport.width}x${viewport.height}`,
    );
    await mkdir(folder, { recursive: true });
    async function check(name: string) {
      await expect(page.locator(".entry-snapshot")).toHaveCount(0);
      await expect(
        page.locator('.collapse-region[data-expanding="true"]'),
      ).toHaveCount(0);
      await expect(page.locator(".route-snapshot")).toHaveCount(0);
      await expect(page.locator(".tab-slide-snapshot")).toHaveCount(0);
      await page
        .locator(".route-screen:not(.route-snapshot)")
        .evaluateAll(async (elements) => {
          await Promise.allSettled(
            elements.flatMap((element) =>
              element.getAnimations().map((animation) => animation.finished),
            ),
          );
        });
      const result = await page.evaluate(() => ({
        horizontal: document.documentElement.scrollWidth - innerWidth,
        vertical: document.documentElement.scrollHeight - innerHeight,
        broken: Array.from(document.images)
          .filter((i) => !i.complete || !i.naturalWidth)
          .map((i) => i.alt),
      }));
      expect(result.horizontal, name).toBeLessThanOrEqual(1);
      expect(result.vertical, name).toBeLessThanOrEqual(2);
      expect(result.broken, name).toEqual([]);
      const workspace = (await page.locator(".business-workspace").count())
          ? await page.locator(".business-workspace").boundingBox()
          : null,
        nav = (await page.locator(".home-navigation").count())
          ? await page.locator(".home-navigation").boundingBox()
          : null;
      if (workspace && nav) {
        expect(workspace.y + workspace.height, name).toBeLessThan(nav.y);
        expect(Math.abs(workspace.x - nav.x), name).toBeLessThan(1);
        expect(Math.abs(workspace.width - nav.width), name).toBeLessThan(1);
      }
      // Primary actions and the promised four rows must be visible without scrolling their outer panel.
      for (const [parentSelector, childSelector] of [
        [".resumes-panel", ".resume-edit-footer .ui-button"],
        [".admin-user-rows", ".admin-user-rows .data-row"],
        [".admin-tasks-body", ".admin-tasks-body .data-row"],
        [".admin-usage-rows", ".admin-usage-rows .data-row"],
      ]) {
        if (!(await page.locator(parentSelector).count())) continue;
        const parent = await page.locator(parentSelector).boundingBox();
        for (const child of await page.locator(childSelector).all()) {
          const rect = await child.boundingBox();
          if (parent && rect)
            expect(
              rect.y + rect.height,
              `${name}: ${childSelector}`,
            ).toBeLessThanOrEqual(parent.y + parent.height + 1);
        }
      }
      await page.screenshot({
        path: resolve(folder, name + ".png"),
        animations: "disabled",
      });
    }
    for (const [name, path] of [
      ["01-home", "/home"],
      ["02-resumes", "/resumes"],
      ["03-jd", "/interview"],
      ["04-prepare", "/interview?tab=prepare"],
      ["05-tasks", "/interview?tab=tasks"],
      ["06-history", "/history"],
      ["07-report", "/reports/interview-6"],
      ["08-partial", "/reports/interview-7"],
      ["09-practice", "/practice/practice-3"],
      ["10-settings", "/settings"],
    ]) {
      await go(page, path!);
      await check(name!);
    }
    await page.getByRole("button", { name: "更换头像", exact: true }).click();
    await check("11-avatar");
    await page.keyboard.press("Escape");
    await go(page, "/resumes");
    await page.getByRole("button", { name: "校对简历", exact: true }).click();
    await check("12-resume-editor");
    await prepare(page);
    await check("13-room");
    await page.getByRole("button", { name: "结束面试", exact: true }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "确认", exact: true })
      .click();
    await go(page, "/reports/interview-6");
    await page.getByRole("tab", { name: "逐题回顾", exact: true }).click();
    await check("14-questions");
    await page.getByRole("tab", { name: "维度评分", exact: true }).click();
    await check("15-dimensions");
    await go(page, "/practice/practice-2");
    await page.getByRole("tab", { name: "变式验证", exact: true }).click();
    await check("16-variant-pending");
    await go(page, "/login");
    await check("17-logo");
    await page
      .getByRole("button", {
        name: "点击 CareerPilot 标志进入登录",
        exact: true,
      })
      .click();
    await expect(page.locator(".auth-page")).toHaveAttribute(
      "data-state",
      "login",
    );
    await check("18-login");
    await adminLogin(page);
    await check("19-admin-users");
    await page.getByRole("tab", { name: "运行概况", exact: true }).click();
    await check("20-admin-overview");
    await page.getByRole("tab", { name: "模型用量", exact: true }).click();
    await check("21-admin-usage");
    expect(errors).toEqual([]);
  });
}
