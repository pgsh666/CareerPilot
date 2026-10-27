import { test, expect, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";

async function mockJobs(page: Page) {
  let job = {
    id: "job-rename-fixture",
    title: "新增岗位 JD",
    status: "confirmed",
    revision: 2,
    version: 1,
    updatedAt: "2026-10-27T00:30:00Z",
    source: "岗位名称：后端开发\n任职要求：Python",
    parsed: true,
    analyzedSource: "岗位名称：后端开发\n任职要求：Python",
    name: "后端开发",
    company: "",
    role: "后端开发",
    direction: "Python",
    responsibilities: "开发接口",
    requirements: "Python",
    inference: "",
    useInference: false,
  };
  const writes: { method: string; body: any }[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(),
      path = new URL(request.url()).pathname;
    if (request.method() !== "GET") {
      const body = request.postDataJSON();
      writes.push({ method: request.method(), body });
      expect(path).toBe(`/api/v1/materials/jobs/${job.id}`);
      if (body.title === "冲突测试" || body.revision !== job.revision)
        return route.fulfill({
          status: 409,
          json: {
            error: {
              code: "MATERIAL_CONFLICT",
              message: "材料已在其他页面更新，请刷新后重新校对",
            },
          },
        });
      if (request.method() === "PATCH")
        job = { ...job, title: body.title, revision: job.revision + 1 };
      else if (request.method() === "PUT")
        job = {
          ...job,
          ...body.fields,
          revision: job.revision + 1,
          version: 2,
        };
      else throw new Error("未预期的写操作");
      return route.fulfill({ json: { material: job } });
    }
    if (path.endsWith("/auth/me"))
      return route.fulfill({
        json: {
          account: {
            id: "rename-user",
            email: "rename@example.org",
            name: "合成验收",
            role: "user",
            enabled: true,
            avatar: "default",
          },
          csrf_token: "fixture",
        },
      });
    if (path.endsWith("/materials/jobs"))
      return route.fulfill({ json: { items: [job], total: 1 } });
    if (path.endsWith("/training/summary"))
      return route.fulfill({
        json: {
          active: null,
          completedInterviews: 0,
          practiceMinutes: 0,
          tasks: [],
        },
      });
    return route.fulfill({ json: { items: [], total: 0 } });
  });
  return { writes, current: () => job };
}

test("JD 重命名支持取消、空白校验、保留编辑草稿并在刷新及材料选择中保留", async ({
  page,
}) => {
  const api = await mockJobs(page);
  await page.goto("/#/interview?job=job-rename-fixture");
  const row = page.locator(".jd-history-row");
  await expect(row.getByLabel("岗位名称", { exact: true })).toBeVisible();
  await row.getByLabel("明确要求", { exact: true }).fill("未保存的校对内容");
  await row.getByRole("button", { name: "重命名", exact: true }).click();
  const modal = page.getByRole("dialog", { name: "重命名岗位 JD" });
  await modal.getByLabel("JD 名称", { exact: true }).fill("取消的名称");
  await modal.getByRole("button", { name: "取消", exact: true }).click();
  expect(api.writes).toHaveLength(0);
  await expect(row.locator("h3")).toHaveText("新增岗位 JD");
  await row.getByRole("button", { name: "重命名", exact: true }).click();
  await modal.getByLabel("JD 名称", { exact: true }).fill("   ");
  await modal.getByRole("button", { name: "保存", exact: true }).click();
  await expect(modal.getByRole("alert")).toContainText("1—180");
  expect(api.writes).toHaveLength(0);
  await modal
    .getByLabel("JD 名称", { exact: true })
    .fill("  目标公司 · 后端实习  ");
  await modal.getByLabel("JD 名称", { exact: true }).press("Enter");
  await expect(row.locator("h3")).toHaveText("目标公司 · 后端实习");
  expect(api.current().version).toBe(1);
  expect(api.current().name).toBe("后端开发");
  await expect(row.getByLabel("明确要求", { exact: true })).toHaveValue(
    "未保存的校对内容",
  );
  await row.getByRole("button", { name: "确认并保存", exact: true }).click();
  await expect.poll(() => api.writes.length).toBe(2);
  expect(api.writes[1]!.body.revision).toBe(3);
  expect(api.current().requirements).toBe("未保存的校对内容");
  await page.reload();
  await expect(row.locator("h3")).toHaveText("目标公司 · 后端实习");
  await page.getByRole("tab", { name: "模拟面试", exact: true }).click();
  await expect(page.getByLabel("本次岗位JD")).toContainText(
    "目标公司 · 后端实习",
  );
});

test("JD 改名冲突保留输入，长名称在四种窗口内不挤压操作", async ({ page }) => {
  const api = await mockJobs(page);
  await page.goto("/#/interview");
  await page.getByRole("button", { name: /历史 JD/ }).click();
  const row = page.locator(".jd-history-row");
  await row.getByRole("button", { name: "重命名", exact: true }).click();
  const modal = page.getByRole("dialog", { name: "重命名岗位 JD" });
  await modal.getByLabel("JD 名称", { exact: true }).fill("冲突测试");
  await modal.getByRole("button", { name: "保存", exact: true }).click();
  await expect(modal.getByRole("alert")).toContainText("刷新");
  await expect(modal.getByLabel("JD 名称", { exact: true })).toHaveValue(
    "冲突测试",
  );
  await expect(row.locator("h3")).toHaveText("新增岗位 JD");
  await modal.getByRole("button", { name: "取消", exact: true }).click();
  await row.getByRole("button", { name: "重命名", exact: true }).click();
  const long = "后端开发实习岗位与公司名称".repeat(12);
  await modal.getByLabel("JD 名称", { exact: true }).fill(long);
  await modal.getByRole("button", { name: "保存", exact: true }).click();
  await expect(row.locator("h3")).toHaveText(long);
  expect(api.current().version).toBe(1);
  await mkdir("../artifacts/job-rename", { recursive: true });
  for (const [width, height] of [
    [1024, 768],
    [1440, 900],
    [1920, 1080],
    [2560, 1440],
  ]) {
    await page.setViewportSize({ width, height });
    await expect(page.locator(".modal-mask")).toHaveCount(0);
    const box = await row.evaluate((el) => {
      const title = el.querySelector("h3")!.getBoundingClientRect();
      const actions = el
        .querySelector(".jd-history-actions")!
        .getBoundingClientRect();
      return {
        gap: actions.left - title.right,
        overflow: document.documentElement.scrollWidth > innerWidth,
      };
    });
    expect(box.gap).toBeGreaterThan(0);
    expect(box.overflow).toBe(false);
    await page.screenshot({
      path: `../artifacts/job-rename/${width}x${height}.png`,
    });
  }
});
