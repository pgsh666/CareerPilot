import { ref } from "vue";
import { api, ApiError, onAuthFailure, setCsrfToken } from "./api";
import { isPreviewMode } from "./runtime";
import {
  activatePreviewAccount,
  activateServiceAccount,
  clearServiceAccount,
  signOut as signOutPreview,
  state,
  type ServiceAccount,
} from "./state";

interface AuthResponse {
  account: ServiceAccount;
  csrf_token: string;
}
export const authNotice = ref("");
export const accountBusy = ref(false);
let revision = 0;
let restoring: Promise<boolean> | null = null;

function invalidate(notice = "") {
  revision++;
  restoring = null;
  setCsrfToken("");
  clearServiceAccount();
  authNotice.value = notice;
}

function publishAuthChange() {
  try {
    localStorage.setItem(
      "careerpilot:auth-change",
      `${Date.now()}:${crypto.randomUUID()}`,
    );
  } catch {
    /* Cookie/session authorization does not depend on local storage. */
  }
}

onAuthFailure((error) => {
  invalidate(error.message);
  window.dispatchEvent(new Event("careerpilot:auth-lost"));
});

export async function restoreSession(): Promise<boolean> {
  if (isPreviewMode) return state.signedIn;
  if (restoring) return restoring;
  const generation = revision;
  const pending = (async () => {
    try {
      const result = await api<AuthResponse>("/auth/me", {
        publicRequest: true,
      });
      if (generation !== revision) return state.signedIn;
      setCsrfToken(result.csrf_token);
      activateServiceAccount(result.account);
      authNotice.value = "";
      return true;
    } catch (error) {
      if (generation !== revision) return state.signedIn;
      const expectedGuest = error instanceof ApiError && error.status === 401;
      invalidate(
        expectedGuest
          ? ""
          : error instanceof Error
            ? error.message
            : "账号状态检查失败",
      );
      return false;
    }
  })();
  restoring = pending;
  try {
    return await pending;
  } finally {
    if (restoring === pending) restoring = null;
  }
}

export async function loginAccount(email: string, password: string) {
  const address = email.trim().toLowerCase();
  if (isPreviewMode) {
    if (
      !["user@example.com", "admin@example.com"].includes(address) ||
      password !== "Pilot@2026"
    )
      throw new ApiError("邮箱或密码不正确", "LOGIN_INVALID", 401);
    activatePreviewAccount(address);
    return;
  }
  const generation = ++revision;
  restoring = null;
  const result = await api<AuthResponse>("/auth/login", {
    method: "POST",
    body: { email: address, password },
    publicRequest: true,
  });
  if (generation !== revision)
    throw new ApiError("账号状态已改变，请重新登录", "ACCOUNT_CHANGED");
  setCsrfToken(result.csrf_token);
  activateServiceAccount(result.account);
  authNotice.value = "";
  publishAuthChange();
}

export async function requestCode(
  email: string,
  purpose: "register" | "password_reset" | "email_change",
) {
  if (isPreviewMode)
    throw new ApiError("邮件服务尚未连接，未发送验证码。", "PREVIEW_MODE");
  if (purpose === "email_change")
    return api<{ message: string }>("/account/email/codes", {
      method: "POST",
      body: { email },
    });
  return api<{ message: string }>("/auth/codes", {
    method: "POST",
    body: { email, purpose },
    publicRequest: true,
  });
}

export async function registerOrReset(
  mode: "register" | "reset",
  body: { email: string; password: string; confirmation: string; code: string },
) {
  if (isPreviewMode)
    throw new ApiError(
      "账号服务尚未连接，未创建账号或重置密码。",
      "PREVIEW_MODE",
    );
  await api(mode === "register" ? "/auth/register" : "/auth/password-reset", {
    method: "POST",
    body,
    publicRequest: true,
  });
  if (mode === "reset") {
    invalidate();
    publishAuthChange();
  }
}

async function exclusive<T>(action: () => Promise<T>): Promise<T> {
  if (accountBusy.value)
    throw new ApiError("操作进行中，请稍候", "OPERATION_PENDING");
  accountBusy.value = true;
  try {
    return await action();
  } finally {
    accountBusy.value = false;
  }
}

export async function saveProfile(body: { name?: string; avatar?: string }) {
  return exclusive(async () => {
    if (isPreviewMode) {
      Object.assign(state.account, body);
      return;
    }
    const owner = state.account.id;
    const generation = revision;
    const result = await api<{ account: ServiceAccount }>("/account/profile", {
      method: "PATCH",
      body,
    });
    if (generation !== revision || state.account.id !== owner)
      throw new ApiError(
        "账号已切换，请在原账号查看操作结果",
        "ACCOUNT_CHANGED",
      );
    revision++;
    restoring = null;
    activateServiceAccount(result.account);
  });
}

export async function uploadAvatar(file: File) {
  return exclusive(async () => {
    if (isPreviewMode) throw new ApiError("请在本机服务页面上传头像", "PREVIEW_MODE");
    const owner = state.account.id, generation = revision;
    const result = await api<{ account: ServiceAccount }>("/account/avatar", { method: "PUT", file });
    if (generation !== revision || owner !== state.account.id)
      throw new ApiError("账号已切换，请在原账号查看上传结果", "ACCOUNT_CHANGED");
    revision++;
    restoring = null;
    activateServiceAccount(result.account);
    publishAuthChange();
  });
}

export async function changePassword(body: {
  current_password: string;
  password: string;
  confirmation: string;
}) {
  return exclusive(async () => {
    if (isPreviewMode)
      throw new ApiError("账号服务尚未连接，密码未修改。", "PREVIEW_MODE");
    await api("/account/password", { method: "POST", body });
    invalidate();
    publishAuthChange();
  });
}

export async function changeEmail(body: { email: string; code: string }) {
  return exclusive(async () => {
    if (isPreviewMode)
      throw new ApiError(
        "账号服务尚未连接，未发送验证码或修改账号。",
        "PREVIEW_MODE",
      );
    await api("/account/email", { method: "POST", body });
    invalidate();
    publishAuthChange();
  });
}

export async function signOut() {
  return exclusive(async () => {
    if (isPreviewMode) {
      signOutPreview();
      return;
    }
    revision++;
    restoring = null;
    try {
      await api("/auth/logout", { method: "POST", publicRequest: true });
    } catch (error) {
      if (
        !(error instanceof ApiError) ||
        (error.status !== 401 && error.code !== "ACCOUNT_UNAVAILABLE")
      )
        throw error;
    }
    invalidate();
    publishAuthChange();
  });
}

export async function closeAccount(email: string) {
  return exclusive(async () => {
    if (isPreviewMode)
      throw new ApiError("账号服务尚未连接，账号未注销。", "PREVIEW_MODE");
    const owner = state.account.id,
      generation = revision;
    await api("/account/close", {
      method: "POST",
      body: { email, confirmed: true },
    });
    if (generation !== revision || owner !== state.account.id)
      throw new ApiError(
        "账号状态已改变，请在原账号查看操作结果",
        "ACCOUNT_CHANGED",
      );
    invalidate("账号已永久关闭，个人数据暂保留。");
    publishAuthChange();
  });
}

if (!isPreviewMode) {
  window.addEventListener("storage", async (event) => {
    if (event.key !== "careerpilot:auth-change") return;
    revision++;
    restoring = null;
    await restoreSession();
    window.dispatchEvent(new Event("careerpilot:auth-rechecked"));
  });
  window.addEventListener("focus", async () => {
    if (!state.signedIn) return;
    await restoreSession();
    window.dispatchEvent(new Event("careerpilot:auth-rechecked"));
  });
}
