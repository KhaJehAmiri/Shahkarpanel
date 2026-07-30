const API_BASE = process.env.NEXT_PUBLIC_BASE_API || "/api/";
const TOKEN_KEY = "nx_portal_token";

export const getPortalToken = () =>
  typeof window !== "undefined" ? localStorage.getItem(TOKEN_KEY) : null;

export const setPortalToken = (t: string) => localStorage.setItem(TOKEN_KEY, t);

export const clearPortalToken = () => localStorage.removeItem(TOKEN_KEY);

export const PORTAL_UNAUTHORIZED_EVENT = "sk-portal-unauthorized";

/** A 401 anywhere means the session is gone — tell the app to show the login. */
function onUnauthorized() {
  clearPortalToken();
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(PORTAL_UNAUTHORIZED_EVENT));
  }
}

async function errorFromResponse(res: Response): Promise<Error> {
  let msg = `HTTP ${res.status}`;
  try {
    const j = await res.json();
    if (j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
  } catch {
    /* ignore */
  }
  return new Error(msg);
}

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
    // The login form itself must not trigger a global session reset.
    if (!path.endsWith("/portal/token")) onUnauthorized();
    throw new Error("401");
  }
  if (!res.ok) throw await errorFromResponse(res);
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
    onUnauthorized();
    throw new Error("401");
  }
  if (!res.ok) throw await errorFromResponse(res);
  if (res.status === 204) return undefined as T;
  return res.json();
}

/** Multipart upload (card receipt). Do not set Content-Type — browser sets boundary. */
export async function portalUpload<T>(path: string, form: FormData): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getPortalToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(apiUrl(path), { method: "POST", headers, body: form });
  if (res.status === 401) {
    onUnauthorized();
    throw new Error("401");
  }
  if (!res.ok) throw await errorFromResponse(res);
  if (res.status === 204) return undefined as T;
  return res.json();
}

export async function portalDelete<T>(path: string): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getPortalToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(apiUrl(path), { method: "DELETE", headers });
  if (res.status === 401) {
    onUnauthorized();
    throw new Error("401");
  }
  if (!res.ok) throw await errorFromResponse(res);
  if (res.status === 204) return undefined as T;
  return res.json();
}
