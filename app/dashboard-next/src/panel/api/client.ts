import i18n from "../i18n";

const BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_BASE_API) || "/api/";

const TOKEN_KEY = "nx_token";
const REFRESH_KEY = "nx_refresh_token";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const getRefreshToken = () => localStorage.getItem(REFRESH_KEY);
export const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t);
export const setRefreshToken = (t: string) => localStorage.setItem(REFRESH_KEY, t);
export const clearToken = () => {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
};

export class ApiError extends Error {
  status: number;
  requires2fa?: boolean;
  /** Raw parsed JSON body of the failed response, when available (e.g. a
   * structured `detail` object) — for callers that need more than the
   * flattened message string `errorMessage()` produces. */
  body?: any;
  constructor(message: string, status: number, requires2fa = false, body?: any) {
    super(message);
    this.status = status;
    this.requires2fa = requires2fa;
    this.body = body;
  }
}

let onUnauthorized: (() => void) | null = null;
export const setUnauthorizedHandler = (fn: () => void) => {
  onUnauthorized = fn;
};

let refreshInFlight: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return null;
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const res = await fetch(joinUrl("/admin/refresh"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
        if (!res.ok) return null;
        const data = await res.json();
        if (!data?.access_token) return null;
        setToken(data.access_token);
        return data.access_token as string;
      } catch {
        return null;
      } finally {
        refreshInFlight = null;
      }
    })();
  }
  return refreshInFlight;
}

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
  if (detail && typeof detail === "object" && typeof detail.message === "string") {
    return detail.message;
  }
  const key = STATUS_ERROR_KEY[status] || "errors.generic";
  return i18n.t(key, { status });
}

type RequestOpts = { form?: boolean; retried?: boolean };

async function request<T>(
  method: string,
  path: string,
  body?: any,
  opts: RequestOpts = {},
): Promise<T> {
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

  if (res.status === 401 && !opts.retried) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      return request<T>(method, path, body, { ...opts, retried: true });
    }
    if (onUnauthorized) onUnauthorized();
    throw new ApiError(i18n.t("errors.unauthorized"), 401);
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
    throw new ApiError(errorMessage(res.status, data), res.status, false, data);
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
  download: async (path: string, fallbackName = "download"): Promise<void> => {
    const headers: Record<string, string> = {};
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    let res: Response;
    try {
      res = await fetch(joinUrl(path), { headers });
    } catch {
      throw new ApiError(i18n.t("errors.network"), 0);
    }
    if (res.status === 401) {
      const refreshed = await refreshAccessToken();
      if (refreshed) {
        headers["Authorization"] = `Bearer ${refreshed}`;
        res = await fetch(joinUrl(path), { headers });
      }
    }
    if (res.status === 401) {
      if (onUnauthorized) onUnauthorized();
      throw new ApiError(i18n.t("errors.unauthorized"), 401);
    }
    if (!res.ok) {
      const text = await res.text();
      let data: any = null;
      try { data = text ? JSON.parse(text) : null; } catch { data = text; }
      throw new ApiError(errorMessage(res.status, data), res.status);
    }
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^"]+)"?/i);
    const name = match?.[1] || fallbackName;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
  getBlob: async (path: string): Promise<{ blob: Blob; contentType: string; filename?: string }> => {
    const headers: Record<string, string> = {};
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    let res: Response;
    try {
      res = await fetch(joinUrl(path), { headers });
    } catch {
      throw new ApiError(i18n.t("errors.network"), 0);
    }
    if (res.status === 401) {
      const refreshed = await refreshAccessToken();
      if (refreshed) {
        headers["Authorization"] = `Bearer ${refreshed}`;
        res = await fetch(joinUrl(path), { headers });
      }
    }
    if (res.status === 401) {
      if (onUnauthorized) onUnauthorized();
      throw new ApiError(i18n.t("errors.unauthorized"), 401);
    }
    if (!res.ok) {
      const text = await res.text();
      let data: any = null;
      try { data = text ? JSON.parse(text) : null; } catch { data = text; }
      throw new ApiError(errorMessage(res.status, data), res.status);
    }
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename\*?=(?:UTF-8''|")?([^\";]+)"?/i);
    const filename = match?.[1] ? decodeURIComponent(match[1]) : undefined;
    const blob = await res.blob();
    const contentType = (res.headers.get("Content-Type") || blob.type || "").split(";")[0].trim();
    return { blob, contentType, filename };
  },
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
      const refreshed = await refreshAccessToken();
      if (refreshed) {
        headers["Authorization"] = `Bearer ${refreshed}`;
        res = await fetch(joinUrl(path), { method: "POST", headers, body: form });
      }
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

export async function login(
  username: string,
  password: string,
  otp?: string,
): Promise<string> {
  const body: Record<string, string> = {
    username,
    password,
    grant_type: "password",
  };
  if (otp) body.otp = otp;

  let res: Response;
  try {
    res = await fetch(joinUrl("/admin/token"), {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams(body).toString(),
    });
  } catch {
    throw new ApiError(i18n.t("errors.network"), 0);
  }

  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }

  if (!res.ok) {
    const requires2fa = res.headers.get("X-2FA-Required") === "true";
    throw new ApiError(errorMessage(res.status, data), res.status, requires2fa);
  }

  setToken(data.access_token);
  if (data.refresh_token) setRefreshToken(data.refresh_token);
  return data.access_token;
}
