const BASE = (import.meta as any).env?.VITE_BASE_API || "/api/";

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

  const res = await fetch(joinUrl(path), { method, headers, body: payload });

  if (res.status === 401) {
    if (onUnauthorized) onUnauthorized();
    throw new ApiError("Unauthorized", 401);
  }

  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }

  if (!res.ok) {
    const detail =
      (data && (data.detail || data.message)) ||
      (typeof data === "string" ? data : `Request failed (${res.status})`);
    const msg = Array.isArray(detail)
      ? detail.map((d: any) => d.msg || JSON.stringify(d)).join(", ")
      : typeof detail === "object"
      ? JSON.stringify(detail)
      : String(detail);
    throw new ApiError(msg, res.status);
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
