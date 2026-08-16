/** Auto Web Push for admin panel — no UI button; prompt like a native app. */

import { api } from "../api/client";

const ASKED_KEY = "nx_push_asked_v1";

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export function isStandaloneDisplay(): boolean {
  if (typeof window === "undefined") return false;
  const mq = window.matchMedia?.("(display-mode: standalone)")?.matches;
  const ios = (navigator as any).standalone === true;
  return !!(mq || ios);
}

export function isIosSafariTab(): boolean {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent || "";
  const iOS =
    /iPad|iPhone|iPod/.test(ua) ||
    (navigator.platform === "MacIntel" && (navigator as any).maxTouchPoints > 1);
  const webkit = /WebKit/.test(ua);
  const chrome = /CriOS|FxiOS|EdgiOS/.test(ua);
  return iOS && webkit && !chrome && !isStandaloneDisplay();
}

export function pushSupported(): boolean {
  if (typeof window === "undefined") return false;
  const secure =
    window.isSecureContext ||
    location.protocol === "https:" ||
    location.hostname === "localhost" ||
    location.hostname === "127.0.0.1";
  if (!secure) return false;
  if (isIosSafariTab()) return false;
  return (
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

export async function ensureServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (!("serviceWorker" in navigator)) return null;
  try {
    const existing = await navigator.serviceWorker.getRegistration("/");
    if (existing) {
      await navigator.serviceWorker.ready;
      return existing;
    }
    const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
    await navigator.serviceWorker.ready;
    return reg;
  } catch (err) {
    console.warn("service worker register failed", err);
    return null;
  }
}

async function postToSw(message: object) {
  try {
    const reg = await ensureServiceWorker();
    reg?.active?.postMessage(message);
  } catch {
    /* ignore */
  }
}

/** Apply Telegram-style home-screen badge (installed PWA). */
export async function setAppBadgeCount(count: number, opts?: { allowClear?: boolean }): Promise<void> {
  const n = Math.max(0, Math.floor(Number(count) || 0));
  try {
    const nav = navigator as Navigator & {
      setAppBadge?: (c?: number) => Promise<void>;
      clearAppBadge?: () => Promise<void>;
    };
    if (n > 0 && typeof nav.setAppBadge === "function") {
      await nav.setAppBadge(Math.min(99, n));
    } else if (n <= 0 && opts?.allowClear !== false && typeof nav.clearAppBadge === "function") {
      await nav.clearAppBadge();
    }
  } catch {
    /* ignore */
  }
  if (n > 0) {
    await postToSw({ type: "sk-set-badge", count: n });
  } else {
    await postToSw({ type: "sk-clear-badge", allowClear: true });
  }
}

/** Sync badge from server (orders awaiting review + unpaid invoices). */
export async function syncAdminAppBadge(): Promise<number> {
  try {
    const { count } = await api.get<{ count: number }>("/push/badge");
    const n = Math.max(0, Number(count) || 0);
    await setAppBadgeCount(n, { allowClear: true });
    return n;
  } catch {
    return 0;
  }
}

/** Subscribe + register with backend. Assumes Notification.permission === 'granted'. */
export async function subscribeWebPush(): Promise<boolean> {
  if (!pushSupported()) return false;
  if (Notification.permission !== "granted") return false;
  const reg = await ensureServiceWorker();
  if (!reg) return false;
  const { publicKey } = await api.get<{ publicKey: string }>("/push/vapid-public-key");
  if (!publicKey) return false;
  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicKey) as BufferSource,
    });
  }
  const json = sub.toJSON();
  if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) return false;
  await api.post("/push/subscribe", {
    endpoint: json.endpoint,
    keys: json.keys,
    expirationTime: json.expirationTime ?? null,
  });
  // Keep credentials in the SW cache so pushsubscriptionchange can refresh
  // the endpoint even while the panel stays closed.
  try {
    const token = localStorage.getItem("nx_token");
    const apiBase =
      (typeof process !== "undefined" && process.env.NEXT_PUBLIC_BASE_API) || "/api/";
    reg.active?.postMessage({
      type: "sk-push-meta",
      meta: {
        vapidPublicKey: publicKey,
        accessToken: token || "",
        apiBase,
        savedAt: Date.now(),
      },
    });
  } catch {
    /* ignore */
  }
  void syncAdminAppBadge();
  return true;
}

/**
 * Ask the browser for notification permission (system dialog), then subscribe.
 */
export async function requestPushPermissionAndSubscribe(): Promise<"granted" | "denied" | "default" | "unsupported"> {
  if (!pushSupported()) return "unsupported";
  let perm = Notification.permission;
  if (perm === "default") {
    try {
      perm = await Notification.requestPermission();
    } catch {
      return "default";
    }
    try {
      localStorage.setItem(ASKED_KEY, "1");
    } catch {
      /* ignore */
    }
  }
  if (perm === "granted") {
    try {
      await subscribeWebPush();
    } catch (err) {
      console.warn("web push subscribe failed", err);
    }
  }
  return perm;
}

export function wasPushAsked(): boolean {
  try {
    return localStorage.getItem(ASKED_KEY) === "1";
  } catch {
    return false;
  }
}

/** Keep home-screen badge in sync while the panel is open. */
export function bindAdminBadgeLifecycle(): () => void {
  if (typeof window === "undefined") return () => undefined;
  const sync = () => {
    void syncAdminAppBadge();
  };
  const resub = () => {
    if (Notification.permission === "granted") {
      void subscribeWebPush().catch(() => undefined);
    }
  };
  sync();
  resub();
  const onVis = () => {
    if (document.visibilityState === "visible") {
      sync();
      resub();
    }
  };
  document.addEventListener("visibilitychange", onVis);
  window.addEventListener("focus", sync);
  window.addEventListener("focus", resub);
  const onMsg = (event: MessageEvent) => {
    if (event.data?.type === "sk-push-opened") sync();
    if (event.data?.type === "sk-push-resubscribe") resub();
  };
  navigator.serviceWorker?.addEventListener?.("message", onMsg as EventListener);
  const t = window.setInterval(sync, 60_000);
  // Re-upsert push subscription periodically so Apple/FCM endpoint stays fresh.
  const tSub = window.setInterval(resub, 6 * 60 * 60 * 1000);
  return () => {
    document.removeEventListener("visibilitychange", onVis);
    window.removeEventListener("focus", sync);
    window.removeEventListener("focus", resub);
    navigator.serviceWorker?.removeEventListener?.("message", onMsg as EventListener);
    window.clearInterval(t);
    window.clearInterval(tSub);
  };
}
