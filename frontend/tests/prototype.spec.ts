import { test, expect } from "@playwright/test";
import { mkdir, readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { createHash } from "node:crypto";
import { signInPreview } from "./auth";
test.beforeEach(async ({ page }) => {
  await signInPreview(page);
});

const artifacts = resolve("../artifacts/frontend-home");

test("首页保留已确认结构，三个轮播只切换轮播内容", async ({ page }) => {
  await page.goto("/#/home");
  await expect(
    page.getByRole("heading", {
      name: "围绕目标岗位，练好每一次面试",
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.locator(".card-title")).toHaveText([
    "继续上一次练习",
    "薄弱项复练",
    "训练回顾",
  ]);
  await expect(
    page.getByRole("navigation", { name: "主导航" }).getByRole("link"),
  ).toHaveText(["首页", "面试", "简历", "历史", "设置"]);
  await expect(
    page.locator(".sidebar,.topbar-actions,.roles-section"),
  ).toHaveCount(0);
  await expect(
    page.getByRole("progressbar", { name: "面试进度" }),
  ).toHaveAttribute("aria-valuenow", "0");
  await expect(page.locator(".continuation-card .progress-label")).toHaveText(
    "暂无进行中的面试",
  );
  const initialCards = await page.locator(".home-cards").boundingBox();
  await page.getByRole("tab", { name: "产品特色", exact: true }).click();
  await expect(page.locator(".capability")).toHaveCount(3);
  await expect(
    page
      .locator(".home-carousel")
      .getByRole("link", { name: "开始新面试", exact: true }),
  ).toHaveCount(0);
  await expect(page.locator(".feature-introduction h1")).toHaveText(
    "个性化提问，针对性练习",
  );
  expect(await page.locator(".home-cards").boundingBox()).toEqual(initialCards);
  await page.getByRole("tab", { name: "更新公告", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "练习更自然，复盘更清晰", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /查看更新详情/ })).toBeVisible();
  expect(await page.locator(".home-cards").boundingBox()).toEqual(initialCards);
  await page.getByRole("tab", { name: "产品介绍", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(
    page.getByRole("tab", { name: "产品特色", exact: true }),
  ).toBeFocused();
  await expect(
    page.getByRole("tab", { name: "产品特色", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
});

for (const viewport of [
  { width: 1024, height: 768 },
  { width: 1280, height: 720 },
  { width: 1366, height: 768 },
  { width: 1440, height: 900 },
  { width: 1536, height: 864 },
  { width: 1920, height: 1080 },
  { width: 1920, height: 768 },
  { width: 2560, height: 1440 },
]) {
  test(
    "桌面布局 " +
      viewport.width +
      "x" +
      viewport.height +
      "：三卡并排、五项底栏、无重叠",
    async ({ page }) => {
      await page.setViewportSize(viewport);
      await page.goto("/#/home");
      await page.evaluate(() => document.fonts.ready);
      const directory = resolve(
        artifacts,
        viewport.width + "x" + viewport.height,
      );
      await mkdir(directory, { recursive: true });
      for (const [tab, filename] of [
        ["产品介绍", "01-首页"],
        ["产品特色", "02-产品特色"],
        ["更新公告", "03-更新公告"],
      ]) {
        await page.getByRole("tab", { name: tab, exact: true }).click();
        await expect(page.locator(".carousel-slide-snapshot")).toHaveCount(0);
        const geometry = await page.evaluate(() => {
          const box = (selector: string) => {
            const r = document.querySelector(selector)!.getBoundingClientRect();
            return {
              x: r.x,
              y: r.y,
              width: r.width,
              height: r.height,
              right: r.right,
              bottom: r.bottom,
            };
          };
          const cards = [...document.querySelectorAll(".home-card")].map(
            (e) => {
              const r = e.getBoundingClientRect();
              return { x: r.x, y: r.y, right: r.right, bottom: r.bottom };
            },
          );
          const collisions: string[] = [];
          for (const card of document.querySelectorAll(".home-card")) {
            const heading = card
              .querySelector(".card-title")!
              .getBoundingClientRect();
            const more = card
              .querySelector(".card-more")
              ?.getBoundingClientRect();
            if (more && heading.right > more.x - 3)
              collisions.push("标题和角标重叠");
          }
          const hint = document
            .querySelector(".priority-hint")!
            .getBoundingClientRect();
          const action = document
            .querySelector(".practice-card .card-action")!
            .getBoundingClientRect();
          if (hint.bottom > action.y - 2) collisions.push("建议与复练按钮重叠");
          for (const element of document.querySelectorAll(
            ".hero-title,.hero-copy,.feature-eyebrow,.capability h2,.capability p,.capability-foot,.card-title,.priority-title,.training-metrics dt",
          )) {
            if (element.scrollWidth > element.clientWidth + 1)
              collisions.push(element.textContent || "");
          }
          return {
            hero: box(".home-carousel"),
            avatar: box(".user-avatar"),
            logo: box(".brand-logo"),
            cards,
            nav: box(".home-navigation"),
            horizontalOverflow:
              document.documentElement.scrollWidth - innerWidth,
            verticalOverflow:
              document.documentElement.scrollHeight - innerHeight,
            collisions,
            brokenImages: [...document.images]
              .filter((i) => !i.complete || !i.naturalWidth)
              .map((i) => i.alt),
          };
        });
        expect(geometry.horizontalOverflow).toBeLessThanOrEqual(1);
        expect(geometry.verticalOverflow).toBeLessThanOrEqual(2);
        expect(geometry.collisions, JSON.stringify(geometry)).toEqual([]);
        expect(geometry.brokenImages).toEqual([]);
        expect(geometry.avatar.width).toBeLessThan(geometry.logo.width);
        expect(geometry.avatar.width).toBeLessThanOrEqual(56);
        expect(geometry.cards[0]!.y).toBe(geometry.cards[1]!.y);
        expect(geometry.cards[1]!.y).toBe(geometry.cards[2]!.y);
        expect(geometry.hero.bottom).toBeLessThan(geometry.cards[0]!.y);
        expect(geometry.cards[0]!.right).toBeLessThan(geometry.cards[1]!.x);
        expect(geometry.cards[2]!.bottom).toBeLessThan(geometry.nav.y);
        expect(Math.abs(geometry.hero.x - geometry.nav.x)).toBeLessThan(1);
        expect(Math.abs(geometry.hero.right - geometry.nav.right)).toBeLessThan(
          1,
        );
        await page.screenshot({
          path: resolve(directory, filename + ".png"),
          fullPage: true,
        });
      }
    },
  );
}

test("首页入口进入Vue页面，导航可返回首页", async ({ page }) => {
  await page.goto("/#/home");
  await page
    .locator(".home-carousel")
    .getByRole("link", { name: "开始新面试", exact: true })
    .click();
  await expect(page.locator(".interview-materials")).toBeVisible();
  await page
    .getByRole("navigation", { name: "主导航" })
    .getByRole("link", { name: "首页", exact: true })
    .click();
  for (const [name, selector] of [
    ["面试", ".interview-panel"],
    ["简历", ".resumes-panel"],
    ["历史", ".trend-panel"],
    ["设置", ".settings-panel"],
  ]) {
    await page
      .getByRole("navigation", { name: "主导航" })
      .getByRole("link", { name, exact: true })
      .click();
    await expect(page.locator(".route-snapshot")).toHaveCount(0);
    await expect(page.locator(selector)).toBeVisible();
    expect(page.url()).toContain("/#");
    await page
      .getByRole("navigation", { name: "主导航" })
      .getByRole("link", { name: "首页", exact: true })
      .click();
    await expect(page.locator(".route-snapshot")).toHaveCount(0);
    await expect(page.locator(".home-carousel")).toBeVisible();
  }
  await page.locator(".continuation-card .card-action").click();
  await expect(page.locator(".interview-materials")).toBeVisible();
  await page
    .getByRole("navigation", { name: "主导航" })
    .getByRole("link", { name: "首页", exact: true })
    .click();
  await page
    .getByRole("link", { name: "查看全部3项复练任务", exact: true })
    .click();
  await expect(page.locator(".practice-tasks")).toBeVisible();
});


