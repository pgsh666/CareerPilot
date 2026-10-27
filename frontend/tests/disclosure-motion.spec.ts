import {
  test,
  expect,
  chromium,
  type Page,
  type Locator,
} from "@playwright/test";
import { signInPreview } from "./auth";

async function go(page: Page, path: string) {
  await page.goto("/#" + path);
  await expect(page.locator(".route-snapshot")).toHaveCount(0);
}
async function admin(page: Page) {
  await page.goto("/#/login?form=login");
  await page.getByLabel("邮箱", { exact: true }).fill("admin@example.com");
  await page.getByLabel("密码", { exact: true }).fill("Pilot@2026");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/#\/home$/);
  await go(page, "/admin");
}
async function samplePicker(select: Locator, event: "pointerdown" | "keydown") {
  await select.evaluate((element, event) => {
    const runtime = window as typeof window & {
      pickerSamples: number[];
      pickerSampleDone: boolean;
    };
    runtime.pickerSamples = [];
    runtime.pickerSampleDone = false;
    element.addEventListener(
      event,
      () => {
        const start = performance.now();
        const sample = () => {
          runtime.pickerSamples.push(
            Number(getComputedStyle(element, "::picker(select)").opacity),
          );
          if (performance.now() - start < 420) requestAnimationFrame(sample);
          else runtime.pickerSampleDone = true;
        };
        requestAnimationFrame(sample);
      },
      { once: true },
    );
  }, event);
}

test("顶部名称和头像靠右，与Logo左右留白对称，长名称不会挤压Logo", async ({
  page,
}) => {
  await signInPreview(page);
  for (const viewport of [
    { width: 1024, height: 768 },
    { width: 1440, height: 900 },
    { width: 2560, height: 1440 },
  ]) {
    await page.setViewportSize(viewport);
    const geometry = await page.evaluate(() => {
      const brand = document
        .querySelector(".home-brand")!
        .getBoundingClientRect();
      const user = document
        .querySelector(".home-user")!
        .getBoundingClientRect();
      return {
        left: brand.left,
        right: innerWidth - user.right,
        gap: user.left - brand.right,
      };
    });
    expect(Math.abs(geometry.left - geometry.right)).toBeLessThan(1);
    expect(geometry.gap).toBeGreaterThan(40);
  }
  await go(page, "/settings");
  await page
    .getByLabel("用户名", { exact: true })
    .fill("这是一个用于检查顶部布局的很长显示名称".repeat(3));
  await page.getByRole("button", { name: "保存修改", exact: true }).click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - innerWidth,
    ),
  ).toBe(0);
});

for (const channel of ["chrome", "msedge"]) {
  test(`${channel}下拉列表展开收起都有过渡，保留原生选择和Esc操作`, async () => {
    const browser = await chromium.launch({ channel, headless: true });
    const page = await browser.newPage();
    try {
      await page.goto("/#/login?form=login");
      await page.getByLabel("邮箱", { exact: true }).fill("admin@example.com");
      await page.getByLabel("密码", { exact: true }).fill("Pilot@2026");
      await page.getByRole("button", { name: "登录", exact: true }).click();
      await expect(page).toHaveURL(/#\/home$/);
      await page.goto("/#/admin");
      await expect(page.locator(".route-snapshot")).toHaveCount(0);
      await page.getByRole("tab", { name: "模型用量", exact: true }).click();
      await expect(page.locator(".tab-slide-snapshot")).toHaveCount(0);
      const select = page.getByRole("combobox", {
        name: "模型调用用途",
        exact: true,
      });
      await samplePicker(select, "pointerdown");
      await select.click();
      await page.waitForFunction(() => (window as any).pickerSampleDone);
      const opening = await page.evaluate(
        () => (window as any).pickerSamples as number[],
      );
      expect(opening.some((value) => value > 0 && value < 1)).toBe(true);
      await samplePicker(select, "keydown");
      await page.keyboard.press("Escape");
      await page.waitForFunction(() => (window as any).pickerSampleDone);
      const closing = await page.evaluate(
        () => (window as any).pickerSamples as number[],
      );
      expect(closing.some((value) => value > 0 && value < 1)).toBe(true);
      await select.selectOption("报告生成");
      await expect(select).toHaveValue("报告生成");
      await expect(page.locator(".admin-usage-rows strong")).toHaveText([
        "报告生成",
        "报告生成",
        "报告生成",
        "报告生成",
      ]);
    } finally {
      await browser.close();
    }
  });
}

test("简历校对区域平滑展开收起，快速切换不会卡住，更多菜单双向过渡", async ({
  page,
}) => {
  await signInPreview(page);
  await go(page, "/resumes");
  const record = page.locator(".resume-record").first();
  const collapsed = (await record.boundingBox())!.height;
  await page.getByRole("button", { name: "校对简历", exact: true }).click();
  const animation = await record
    .locator(".collapse-region")
    .evaluate((element) => {
      const animation = element.getAnimations()[0]!;
      animation.pause();
      animation.currentTime = 250;
      return {
        height: element.getBoundingClientRect().height,
        duration: animation.effect!.getTiming().duration,
      };
    });
  expect(animation.height).toBeGreaterThan(0);
  expect(animation.duration).toBe(500);
  await page.evaluate(() =>
    document.getAnimations().forEach((animation) => animation.finish()),
  );
  await expect(
    page.locator('.collapse-region[data-expanding="true"]'),
  ).toHaveCount(0);
  const expanded = (await record.boundingBox())!.height;
  expect(expanded).toBeGreaterThan(collapsed);
  await page.getByRole("button", { name: "收起校对", exact: true }).click();
  expect(
    await record
      .locator(".collapse-region")
      .evaluate((element) => element.getAnimations().length),
  ).toBeGreaterThan(0);
  await expect(
    page.locator('.collapse-region[data-expanding="true"]'),
  ).toHaveCount(0);
  expect((await record.boundingBox())!.height).toBeCloseTo(collapsed, 0);
  await page.getByRole("button", { name: "校对简历", exact: true }).click();
  await page.getByRole("button", { name: "收起校对", exact: true }).click();
  await expect(
    page.locator('.collapse-region[data-expanding="true"]'),
  ).toHaveCount(0);
  const second = page.locator(".resume-record").nth(1);
  await second.getByRole("button", { name: "编辑", exact: true }).click();
  await expect(
    page.locator('.collapse-region[data-expanding="true"]'),
  ).toHaveCount(0);
  await expect
    .poll(async () => {
      const row = (await second.boundingBox())!;
      const list = (await page.locator(".resume-list").boundingBox())!;
      return Math.abs(row.y - list.y);
    })
    .toBeLessThan(2);
  await second.getByRole("button", { name: "收起编辑", exact: true }).click();
  await expect(
    page.locator('.collapse-region[data-expanding="true"]'),
  ).toHaveCount(0);
  const more = record.getByRole("button", { name: /更多操作/ });
  await more.click();
  expect(
    await record
      .locator(".resume-menu")
      .evaluate((element) => element.getAnimations().length),
  ).toBeGreaterThan(0);
  await more.click();
  await expect(
    record.getByRole("button", { name: "下载原文件", exact: true }),
  ).toHaveCount(0);
  await expect(record.locator(".resume-menu")).toHaveCount(0);
});

test("历史JD与新增视图双向滑动，推断内容平滑折叠", async ({ page }) => {
  await signInPreview(page);
  await go(page, "/interview");
  await page.getByRole("button", { name: /历史 JD/ }).click();
  await expect(page.locator(".tab-slide-snapshot")).toHaveCount(1);
  await expect(page.locator(".tab-slide-snapshot")).toHaveCount(0);
  await page.getByRole("button", { name: "新增 JD", exact: true }).click();
  await expect(page.locator(".tab-slide-snapshot")).toHaveCount(1);
  await expect(page.locator(".tab-slide-snapshot")).toHaveCount(0);
  await page
    .getByRole("textbox", { name: "粘贴岗位JD原文", exact: true })
    .fill("后端开发岗位，负责接口设计与数据库设计。");
  await page.getByRole("button", { name: "解析 JD", exact: true }).click();
  const details = page.locator(".jd-inference");
  await details.evaluate((element) => {
    const runtime = window as any;
    runtime.detailHeights = [];
    runtime.detailSampleDone = false;
    element.addEventListener(
      "click",
      () => {
        const start = performance.now();
        const sample = () => {
          runtime.detailHeights.push(
            parseFloat(
              getComputedStyle(element, "::details-content").blockSize,
            ),
          );
          if (performance.now() - start < 480) requestAnimationFrame(sample);
          else runtime.detailSampleDone = true;
        };
        requestAnimationFrame(sample);
      },
      { once: true },
    );
  });
  await details.locator("summary").click();
  await expect(details).toHaveAttribute("open", "");
  await page.waitForFunction(() => (window as any).detailSampleDone);
  const heights = await page.evaluate(
    () => (window as any).detailHeights as number[],
  );
  expect(
    heights.some(
      (height) => height > 0 && height < heights[heights.length - 1]! - 1,
    ),
  ).toBe(true);
  await details.locator("summary").click();
  await expect(details).not.toHaveAttribute("open", "");
});

for (const practice of [false, true]) {
  test(`${practice ? "复练" : "面试"}提交后滑到下一阶段且只记录一次回答`, async ({
    page,
  }) => {
    await signInPreview(page);
    if (practice) {
      await go(page, "/interview?tab=tasks&task=idempotency");
      await page.getByRole("button", { name: "开始复练", exact: true }).click();
    } else {
      await go(page, "/interview?tab=prepare");
      await page
        .getByRole("checkbox", { name: "确认使用以上岗位信息和简历" })
        .check();
      await page.getByRole("button", { name: "进入面试", exact: true }).click();
    }
    await expect(page.locator(".route-snapshot")).toHaveCount(0);
    await page
      .getByRole("textbox", { name: "回答文字", exact: true })
      .fill("这是一份用于验证提交动画的实际回答");
    await page.getByRole("button", { name: "提交回答", exact: true }).click();
    await expect(page.locator(".tab-slide-snapshot")).toHaveCount(1);
    const sample = await page
      .locator(".room-panel > .tab-slide-viewport > .tab-slide-pane")
      .evaluate((element) => ({
        animations: element.getAnimations().length,
        opacity: getComputedStyle(element).opacity,
      }));
    expect(sample.animations).toBeGreaterThan(0);
    expect(sample.opacity).toBe("1");
    await expect(page.locator(".tab-slide-snapshot")).toHaveCount(0);
    const count = await page.evaluate(
      () =>
        JSON.parse(localStorage.getItem("careerpilot:frontend:v2")!).session
          .answers.length,
    );
    expect(count).toBe(1);
    if (practice)
      await expect(page.locator(".room-feedback")).toContainText(
        "这是一份用于验证提交动画的实际回答",
      );
    else await expect(page.locator(".room-top")).toContainText("追问 1 / 2");
  });
}

test("减少动态效果时展开、菜单和弹窗仍立即可用", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await signInPreview(page);
  await go(page, "/resumes");
  await page.getByRole("button", { name: "校对简历", exact: true }).click();
  await expect(
    page.locator('.collapse-region[data-expanding="true"]'),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "收起校对", exact: true }).click();
  await page.getByRole("button", { name: "上传简历", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "取消", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
