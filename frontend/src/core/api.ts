import { trainingLeaseHeaders } from "./trainingLease";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly code: string,
    public readonly status = 0,
    public readonly requestId?: string,
  ) {
    super(message);
  }
}

let csrfToken = "";
let sessionEpoch = 0;
let authFailureHandler: ((error: ApiError) => void) | undefined;

export function setCsrfToken(value: string) {
  if (csrfToken === value) return;
  csrfToken = value;
  sessionEpoch++;
}

export function onAuthFailure(handler: (error: ApiError) => void) {
  authFailureHandler = handler;
}

export async function api<T>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    file?: Blob;
    timeoutMs?: number;
    headers?: Record<string, string>;
    responseType?: "blob";
    publicRequest?: boolean;
    keepalive?: boolean;
  } = {},
): Promise<T> {
  const method = options.method || "GET";
  const headers: Record<string, string> = { ...trainingLeaseHeaders(path), ...options.headers };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (options.file) headers["Content-Type"] = "application/octet-stream";
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  const controller = new AbortController();
  const timer = setTimeout(
    () => controller.abort(),
    options.timeoutMs ?? (options.file ? 45_000 : 12_000),
  );
  const requestEpoch = sessionEpoch;
  try {
    const response = await fetch(`/api/v1${path}`, {
      method,
      headers,
      credentials: "include",
      cache: "no-store",
      keepalive: options.keepalive,
      body:
        options.file ||
        (options.body === undefined ? undefined : JSON.stringify(options.body)),
      signal: controller.signal,
    });
    if (response.ok && options.responseType === "blob")
      return (await response.blob()) as T;
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      const error = new ApiError(
        payload?.error?.message || "账号服务暂时无法完成操作，请稍后重试",
        payload?.error?.code || "SERVICE_UNAVAILABLE",
        response.status,
        payload?.error?.request_id,
      );
      if (
        !options.publicRequest &&
        requestEpoch === sessionEpoch &&
        (response.status === 401 || error.code === "ACCOUNT_UNAVAILABLE")
      )
        authFailureHandler?.(error);
      throw error;
    }
    if (payload === null)
      throw new ApiError("账号服务返回异常，请稍后重试", "INVALID_RESPONSE");
    return payload as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(
      controller.signal.aborted
        ? "请求超时，请稍后重试"
        : "无法连接账号服务，请检查后端是否启动",
      controller.signal.aborted ? "REQUEST_TIMEOUT" : "NETWORK_ERROR",
    );
  } finally {
    clearTimeout(timer);
  }
}

export const errorMessage = (error: unknown) =>
  error instanceof Error ? error.message : "操作失败，请稍后重试";
