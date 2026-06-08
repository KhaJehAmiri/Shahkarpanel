const API_BASE = process.env.NEXT_PUBLIC_BASE_API || "/api/";
const TOKEN_KEY = "nx_portal_token";

export const getPortalToken = () =>
  typeof window !== "undefined" ? localStorage.getItem(TOKEN_KEY) : null;

export const setPortalToken = (t: string) => localStorage.setItem(TOKEN_KEY, t);

export const clearPortalToken = () => localStorage.removeItem(TOKEN_KEY);

function apiUrl(path: string): string {
  const base = API_BASE.endsWith("/") ? API_BASE.slice(0, -1) : API_BASE;
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${base}${p}`;
}

async function portalFetch<T>(
  method: string,
  path: string,
  body?: Record<string, string>,
  form = false,
): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getPortalToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let payload: string | undefined;
  if (body) {
    if (form) {
      headers["Content-Type"] = "application/x-www-form-urlencoded";
      payload = new URLSearchParams(body).toString();
    } else {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
  }

  const res = await fetch(apiUrl(path), { method, headers, body: payload });
  if (res.status === 401) {
    clearPortalToken();
    throw new Error("401");
  }
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      if (j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch { /* ignore */ }
    throw new Error(msg);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export async function portalLogin(username: string, password: string) {
  const data = await portalFetch<{ access_token: string }>(
    "POST",
    "/portal/token",
    { username, password, grant_type: "password" },
    true,
  );
  setPortalToken(data.access_token);
}

export const portalGet = <T>(path: string) => portalFetch<T>("GET", path);

export async function portalPost<T>(path: string, body: object): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getPortalToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(apiUrl(path), {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (res.status === 401) {
    clearPortalToken();
    throw new Error("401");
  }
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      if (j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch { /* ignore */ }
    throw new Error(msg);
  }
  return res.json();
}
