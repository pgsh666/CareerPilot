import { fileURLToPath } from "node:url";
import { test, expect } from '@playwright/test';
import { execFile } from 'node:child_process';
import { randomUUID } from 'node:crypto';

function fixture(body: Record<string, unknown>): Promise<{ id: string; email: string; password: string }> {
  return new Promise((resolve, reject) => {
    const child = execFile((process.env.CAREERPILOT_PYTHON || "python"), [fileURLToPath(new URL("../../backend/scripts/auth_browser_fixture.py", import.meta.url))],
      { windowsHide: true, timeout: 15000 }, (error, stdout) => {
        if (error) reject(new Error('Avatar test account operation failed'));
        else resolve(JSON.parse(stdout));
      });
    child.stdin?.end(JSON.stringify(body));
  });
}

test('头像选择预览后取消不保存，确认上传后顶部与设置同步并跨刷新保留，可恢复默认头像', async ({ page }) => {
  const email = `browser-auth-${randomUUID().replaceAll('-', '')}-a@example.org`;
  const user = await fixture({ action: 'prepare', email });
  try {
    await page.goto('/#/login?form=login');
    await page.getByLabel('邮箱', { exact: true }).fill(user.email);
    await page.getByLabel('密码', { exact: true }).fill(user.password);
    await page.getByRole('button', { name: '登录', exact: true }).click();
    await expect(page).toHaveURL(/#\/home$/);
    await page.goto('/#/settings');
    await page.getByRole('button', { name: '更换头像', exact: true }).click();
    await page.getByLabel('选择头像图片').setInputFiles({name: "avatar.png", mimeType: "image/png", buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aVNcAAAAASUVORK5CYII=", "base64")});
    await expect(page.getByAltText('头像上传预览')).toBeVisible();
    await page.getByRole('dialog').getByRole('button', { name: '取消', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    expect((await (await page.request.get('/api/v1/auth/me')).json()).account.avatar).toBe('default');

    await page.getByRole('button', { name: '更换头像', exact: true }).click();
    await page.getByLabel('选择头像图片').setInputFiles({name: "avatar.png", mimeType: "image/png", buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aVNcAAAAASUVORK5CYII=", "base64")});
    await expect(page.getByAltText('头像上传预览')).toBeVisible();
    await page.getByRole('dialog').getByRole('button', { name: '确认', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    const url = (await (await page.request.get('/api/v1/auth/me')).json()).account.avatarUrl;
    await expect(page.locator('.user-avatar img')).toHaveAttribute('src', url);
    await expect(page.getByAltText('当前头像')).toHaveAttribute('src', url);
    await expect.poll(() => page.getByAltText('当前头像').evaluate((i: HTMLImageElement) => i.naturalWidth)).toBe(256);
    await page.reload();
    await expect(page.getByAltText('当前头像')).toHaveAttribute('src', url);
    await page.getByRole('button', { name: '更换头像', exact: true }).click();
    await page.getByRole('button', { name: '使用默认头像', exact: true }).click();
    await page.getByRole('dialog').getByRole('button', { name: '确认', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.getByAltText('当前头像')).toHaveCount(0);
    expect((await page.request.get(url)).status()).toBe(404);
  } finally {
    await page.goto('/#/login?form=login');
    await fixture({ action: 'cleanup', emails: [email] });
  }
});
