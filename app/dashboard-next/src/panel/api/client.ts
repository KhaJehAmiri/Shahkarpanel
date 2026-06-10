import i18n from "../i18n";

const BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_BASE_API) || "/api/";

const TOKEN_KEY = "nx_token";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

let onUnauthorized: (() => void) | null = null;
export const setUnauthorizedHandler = (fn: () => void) => {
  onUnauthorized = fn;
};

function joinUrl(path: string): string {
  if (path.startsWith("http")) return path;
  const b = BASE.endsWith("/") ? BASE.slice(0, -1) : BASE;
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${b}${p}`;
}

const STATUS_ERROR_KEY: Record<number, string> = {
  400: "errors.badRequest",
  403: "errors.forbidden",
  404: "errors.notFound",
  409: "errors.conflict",
  422: "errors.validation",
  429: "errors.tooMany",
  500: "errors.server",
  502: "errors.server",
  503: "errors.server",
  504: "errors.server",
};

/**
 * Turn an HTTP failure into a user-facing message. Backend `detail` strings
 * (e.g. "User already exists") are kept as-is; bare statuses and JSON blobs
 * become localized messages instead of "Request failed (503)".
 */
function errorMessage(status: number, data: any): string {
  const detail = data && (data.detail || data.message);
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const msgs = detail.map((d: any) => d?.msg).filter(Boolean);
    if (msgs.length) return msgs.join(", ");
  }
  const key = STATUS_ERROR_KEY[status] || "errors.generic";
  return i18n.t(key, { status });
}

async function request<T>(method: string, path: string, body?: any, opts: { form?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let payload: any = undefined;
  if (body !== undefined) {
    if (opts.form) {
      headers["Content-Type"] = "application/x-www-form-urlencoded";
      payload = new URLSearchParams(body).toString();
    } else {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
  }

  let res: Response;
  try {
    res = await fetch(joinUrl(path), { method, headers, body: payload });
  } catch {
    throw new ApiError(i18n.t("errors.network"), 0);
  }

  if (res.status === 401) {
    if (onUnauthorized) onUnauthorized();
    throw new ApiError(i18n.t("errors.unauthorized"), 401);
  }

  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }

  if (!res.ok) {
    throw new ApiError(errorMessage(res.status, data), res.status);
  }

  return data as T;
}

export const api = {
  get: <T = any>(path: string) => request<T>("GET", path),
  post: <T = any>(path: string, body?: any) => request<T>("POST", path, body),
  put: <T = any>(path: string, body?: any) => request<T>("PUT", path, body),
  patch: <T = any>(path: string, body?: any) => request<T>("PATCH", path, body),
  del: <T = any>(path: string, body?: any) => request<T>("DELETE", path, body),
  postForm: <T = any>(path: string, body: Record<string, string>) =>
    request<T>("POST", path, body, { form: true }),
  upload: async <T = any>(path: string, form: FormData): Promise<T> => {
    const headers: Record<string, string> = {};
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    let res: Response;
    try {
      res = await fetch(joinUrl(path), { method: "POST", headers, body: form });
    } catch {
      throw new ApiError(i18n.t("errors.network"), 0);
    }
    if (res.status === 401) {
      if (onUnauthorized) onUnauthorized();
      throw new ApiError(i18n.t("errors.unauthorized"), 401);
    }
    const text = await res.text();
    let data: any = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = text; }
    if (!res.ok) {
      throw new ApiError(errorMessage(res.status, data), res.status);
    }
    return data as T;
  },
};

export async function login(username: string, password: string): Promise<string> {
  const res = await api.postForm<{ access_token: string }>("/admin/token", {
    username,
    password,
    grant_type: "password",
  });
  setToken(res.access_token);
  return res.access_token;
}
