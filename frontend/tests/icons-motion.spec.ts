import { test, expect, type Locator, type Page } from "@playwright/test";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";
import { mkdir } from "node:fs/promises";
import { signInPreview } from "./auth";

async function go(page: Page, path: string) {
  await page.goto("/#" + path);
  await expect(page.locator(".route-snapshot")).toHaveCount(0);
}
async function monitor(icon: Locator) {
  await icon.evaluate((element) => {
    const path = element.querySelector("path")!;
    const runtime = window as any;
    runtime.iconWrites = [];
    runtime.iconObserver?.disconnect();
    runtime.iconObserver = new MutationObserver(() =>
      runtime.iconWrites.push(path.getAttribute("d")),
    );
    runtime.iconObserver.observe(path, {
      attributes: true,
      attributeFilter: ["d"],
    });
  });
}
async function finishShape(icon: Locator, filled?: boolean) {
  await expect
    .poll(async () => {
      const first = await icon.locator("path").getAttribute("d");
      await new Promise((resolve) => setTimeout(resolve, 100));
      const second = await icon.locator("path").getAttribute("d");
      return first === second;
    })
    .toBe(true);
  if (filled !== undefined)
    await expect(icon.locator("path")).toHaveAttribute(
      "fill",
      filled ? "currentColor" : "none",
    );
}

test("五项导航使用官方同义图标，悬停与选中进行真实路径形变且无布局跳动", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await signInPreview(page);
  await page.locator(".home-carousel").hover();
  const nav = page.getByRole("navigation", { name: "主导航" });
  await expect(nav.locator("img")).toHaveCount(0);
  await expect(nav.locator(".navigation-icon")).toHaveCount(5);
  for (const [index, name] of [
    "home",
    "interview",
    "resume",
    "history",
    "settings",
  ].entries())
    await expect(nav.locator(".navigation-icon").nth(index)).toHaveAttribute(
      "data-icon",
      name,
    );
  const settings = nav.getByRole("link", { name: "设置", exact: true });
  const icon = settings.locator("svg");
  const beforeBox = await nav.boundingBox();
  const before = await icon.locator("path").getAttribute("d");
  await icon.evaluate((element) => ((window as any).originalIcon = element));
  await monitor(icon);
  await settings.hover();
  await expect(icon).toHaveAttribute("data-icon-emphasized", "true");
  await expect
    .poll(() => page.evaluate(() => new Set((window as any).iconWrites).size))
    .toBeGreaterThan(5);
  await finishShape(icon, true);
  expect(await icon.locator("path").getAttribute("d")).not.toBe(before);
  expect(await nav.boundingBox()).toEqual(beforeBox);
  await settings.click();
  await expect(page).toHaveURL(/#\/settings$/);
  expect(
    await icon.evaluate((element) => element === (window as any).originalIcon),
  ).toBe(true);
  await page.mouse.move(0, 0);
  await page.evaluate(() => (document.activeElement as HTMLElement)?.blur());
  await expect(icon).toHaveAttribute("data-icon-emphasized", "true");
  await finishShape(icon, true);
  await nav.getByRole("link", { name: "历史", exact: true }).click();
  await page.mouse.move(0, 0);
  await finishShape(icon, false);
  await mkdir("../artifacts/morphicons", { recursive: true });
  await page.screenshot({ path: "../artifacts/morphicons/history.png" });
  expect(errors).toEqual([]);
});

test("快速导航、键盘选中和减少动态效果保持正确状态，八种窗口导航尺寸不变", async ({
  page,
}) => {
  await signInPreview(page);
  const nav = page.getByRole("navigation", { name: "主导航" });
  for (const name of ["面试", "简历", "历史", "设置", "首页"])
    await nav
      .getByRole("link", { name, exact: true })
      .evaluate((element) => (element as HTMLElement).click());
  await expect(page).toHaveURL(/#\/home$/);
  await expect(nav.locator('[aria-current="page"]')).toHaveText("首页");
  await page.mouse.move(0, 0);
  const history = nav.getByRole("link", { name: "历史", exact: true });
  await history.focus();
  await expect(history.locator("svg")).toHaveAttribute(
    "data-icon-emphasized",
    "true",
  );
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#\/history$/);
  await page.emulateMedia({ reducedMotion: "reduce" });
  const settings = nav.getByRole("link", { name: "设置", exact: true });
  await monitor(settings.locator("svg"));
  await settings.focus();
  await expect(settings.locator("path")).toHaveAttribute(
    "fill",
    "currentColor",
  );
  await page.waitForTimeout(180);
  expect(
    await page.evaluate(() => new Set((window as any).iconWrites).size),
  ).toBeLessThanOrEqual(2);
  await nav.getByRole("link", { name: "首页", exact: true }).click();
  for (const [width, height] of [
    [1024, 768],
    [1280, 720],
    [1366, 768],
    [1440, 900],
    [1536, 864],
    [1920, 1080],
    [1920, 768],
    [2560, 1440],
  ]) {
    await page.setViewportSize({ width: width!, height: height! });
    const layout = await nav.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return {
        bottom: rect.bottom,
        width: rect.width,
        left: rect.left,
        icons: [...element.querySelectorAll("svg")].map((icon) => {
          const box = icon.getBoundingClientRect();
          return {
            inside: box.top >= rect.top && box.bottom <= rect.bottom,
            width: box.width,
            height: box.height,
          };
        }),
        overflow: document.documentElement.scrollWidth - innerWidth,
      };
    });
    expect(
      layout.icons.every(
        (icon) => icon.inside && Math.abs(icon.width - icon.height) < 1,
      ),
    ).toBe(true);
    expect(layout.bottom).toBeLessThan(height!);
    expect(layout.left * 2 + layout.width).toBeCloseTo(width!, 0);
    expect(layout.overflow).toBe(0);
  }
});

test("密码显隐、简历箭头和更多菜单在同一SVG内变形，保留已有输入与操作", async ({
  page,
}) => {
  await page.goto("/#/login?form=login");
  const password = page.getByLabel("密码", { exact: true });
  await password.fill("Pilot@2026");
  const toggle = page.getByRole("button", { name: "显示密码", exact: true });
  const eye = toggle.locator("svg");
  await eye.evaluate((element) => ((window as any).eyeNode = element));
  await monitor(eye);
  await toggle.click();
  await expect(password).toHaveAttribute("type", "text");
  await expect(page.locator('[data-icon="eye-off"]')).toHaveCount(1);
  await expect
    .poll(() => page.evaluate(() => new Set((window as any).iconWrites).size))
    .toBeGreaterThan(5);
  expect(
    await page
      .locator('[data-icon="eye-off"]')
      .evaluate((element) => element === (window as any).eyeNode),
  ).toBe(true);
  await page.getByRole("button", { name: "隐藏密码", exact: true }).click();
  await expect(password).toHaveValue("Pilot@2026");
  await expect(password).toHaveAttribute("type", "password");
  await page.getByLabel("邮箱", { exact: true }).fill("user@example.com");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/#\/home$/);
  await go(page, "/resumes");
  const row = page.locator(".resume-record").first();
  const arrow = row.locator(".collapse-chevron");
  await arrow.evaluate((element) => ((window as any).arrowNode = element));
  await monitor(arrow);
  await row.getByRole("button", { name: "校对简历", exact: true }).click();
  await expect(arrow).toHaveAttribute("data-icon", "up");
  expect(
    await arrow.evaluate((element) => element === (window as any).arrowNode),
  ).toBe(true);
  await expect
    .poll(() => page.evaluate(() => new Set((window as any).iconWrites).size))
    .toBeGreaterThan(5);
  expect(
    await arrow.evaluate((element) => getComputedStyle(element).transform),
  ).toBe("none");
  await row.getByRole("button", { name: /更多操作/ }).click();
  await expect(row.locator('[data-icon="close"]')).toHaveCount(1);
  await expect(
    row.getByRole("button", { name: "下载原文件", exact: true }),
  ).toBeVisible();
  await row.getByRole("button", { name: /更多操作/ }).click();
  await expect(row.locator('[data-icon="more"]')).toHaveCount(1);
});

test("录音与播报图标随真实语音状态形变，转写和停止功能保留", async ({
  page,
}) => {
  await page.addInitScript(() => {
    speechSynthesis.speak = (utterance) =>
      utterance.onstart?.(new Event("start") as SpeechSynthesisEvent);
    speechSynthesis.cancel = () => {};
    class Recognition {
      onstart?: () => void;
      onend?: () => void;
      onresult?: (event: any) => void;
      start() {
        this.onstart?.();
      }
      stop() {
        this.onresult?.({
          resultIndex: 0,
          results: [{ isFinal: true, 0: { transcript: "实际测试转写" } }],
        });
        this.onend?.();
      }
      abort() {
        this.onend?.();
      }
    }
    Object.defineProperty(window, "SpeechRecognition", {
      value: Recognition,
      configurable: true,
    });
  });
  await signInPreview(page);
  await go(page, "/interview?tab=prepare");
  await page
    .getByRole("checkbox", { name: "确认使用以上岗位信息和简历" })
    .check();
  await page.getByRole("button", { name: "进入面试", exact: true }).click();
  await expect(page.locator(".route-snapshot")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "暂停播报", exact: true }).locator("svg"),
  ).toHaveAttribute("data-icon", "pause");
  await page.getByRole("button", { name: "暂停播报", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "重播问题", exact: true }).locator("svg"),
  ).toHaveAttribute("data-icon", "speaker");
  const mic = page
    .getByRole("button", { name: "开始录音", exact: true })
    .locator("svg");
  await mic.evaluate((element) => ((window as any).micNode = element));
  await monitor(mic);
  await page.getByRole("button", { name: "开始录音", exact: true }).click();
  const stop = page.getByRole("button", { name: "结束录音", exact: true });
  await expect(stop.locator("svg")).toHaveAttribute("data-icon", "stop");
  expect(
    await stop
      .locator("svg")
      .evaluate((element) => element === (window as any).micNode),
  ).toBe(true);
  await expect
    .poll(() => page.evaluate(() => new Set((window as any).iconWrites).size))
    .toBeGreaterThan(5);
  await expect(
    page.getByRole("button", { name: "提交回答", exact: true }),
  ).toBeDisabled();
  await stop.click();
  await expect(page.getByLabel("回答文字", { exact: true })).toHaveValue(
    "实际测试转写",
  );
  await expect(
    page.getByRole("button", { name: "重新录音", exact: true }).locator("svg"),
  ).toHaveAttribute("data-icon", "refresh");
  await expect(
    page.getByRole("button", { name: "提交回答", exact: true }),
  ).toBeEnabled();
});


