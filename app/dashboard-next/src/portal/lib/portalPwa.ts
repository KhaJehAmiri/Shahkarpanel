/** Portal PWA + Web Push helpers */

import { portalGet, portalPost } from "@/lib/portal-api";

const DISMISS_INSTALL_SESSION = "nx_portal_install_skip_session";

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

let deferredInstall: BeforeInstallPromptEvent | null = null;
let installListenerBound = false;

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export function isStandalone(): boolean {
  if (typeof window === "undefined") return false;
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    (navigator as any).standalone === true
  );
}

export function isIos(): boolean {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent || "";
  return (
    /iPad|iPhone|iPod/.test(ua) ||
    (navigator.platform === "MacIntel" && (navigator as any).maxTouchPoints > 1)
  );
}

/** Phone/tablet only — never show “install on phone” on Windows/macOS desktop. */
export function isMobileDevice(): boolean {
  if (typeof window === "undefined" || typeof navigator === "undefined") return false;
  if (isIos()) return true;
  const ua = navigator.userAgent || "";
  if (/Android/i.test(ua)) return true;
  if (/Windows Phone|IEMobile/i.test(ua)) return true;
  if (navigator.platform === "MacIntel" && (navigator as any).maxTouchPoints > 1) return true;
  try {
    const coarse = window.matchMedia("(pointer: coarse)").matches;
    const narrow = window.matchMedia("(max-width: 900px)").matches;
    if (coarse && narrow) return true;
  } catch {
    /* ignore */
  }
  return false;
}

export function hasNativeInstallPrompt(): boolean {
  return deferredInstall != null;
}

export function canShowInstallHint(): boolean {
  if (typeof window === "undefined") return false;
  if (!isMobileDevice()) return false;
  if (isStandalone()) return false;
  try {
    if (sessionStorage.getItem(DISMISS_INSTALL_SESSION) === "1") return false;
  } catch {
    /* ignore */
  }
  return true;
}

export function dismissInstallHint() {
  try {
    sessionStorage.setItem(DISMISS_INSTALL_SESSION, "1");
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new CustomEvent("sk-portal-install-dismissed"));
}

/** Capture Chrome/Edge/Android system install prompt as early as possible. */
export function bindInstallPromptCapture() {
  if (typeof window === "undefined" || installListenerBound) return;
  installListenerBound = true;

  // Desktop (Windows/macOS): never intercept — no “install phone app” UX there.
  if (!isMobileDevice()) return;

  const w = window as Window & { __nxPortalBip?: BeforeInstallPromptEvent };
  if (w.__nxPortalBip) {
    deferredInstall = w.__nxPortalBip;
    w.__nxPortalBip = undefined;
    queueMicrotask(() => window.dispatchEvent(new CustomEvent("sk-portal-install-ready")));
  }

  window.addEventListener("beforeinstallprompt", (e) => {
    if (!isMobileDevice()) return;
    e.preventDefault();
    deferredInstall = e as BeforeInstallPromptEvent;
    w.__nxPortalBip = undefined;
    window.dispatchEvent(new CustomEvent("sk-portal-install-ready"));
  });

  window.addEventListener("appinstalled", () => {
    deferredInstall = null;
    try {
      sessionStorage.setItem(DISMISS_INSTALL_SESSION, "1");
    } catch {
      /* ignore */
    }
    window.dispatchEvent(new CustomEvent("sk-portal-installed"));
  });
}

/**
 * Opens the phone/browser native Install App dialog (Android Chrome/Edge).
 * Must be called from a user gesture (button tap).
 */
export async function promptPortalInstall(): Promise<"accepted" | "dismissed" | "unavailable"> {
  const evt = deferredInstall;
  if (!evt) return "unavailable";
  try {
    await evt.prompt();
    const choice = await evt.userChoice;
    deferredInstall = null;
    if (choice.outcome === "accepted") {
      try {
        sessionStorage.setItem(DISMISS_INSTALL_SESSION, "1");
      } catch {
        /* ignore */
      }
    }
    return choice.outcome;
  } catch (err) {
    console.warn("portal install prompt failed", err);
    return "unavailable";
  }
}

export async function registerPortalSW(): Promise<ServiceWorkerRegistration | null> {
  if (!("serviceWorker" in navigator)) return null;
  const secure =
    window.isSecureContext ||
    location.protocol === "https:" ||
    location.hostname === "localhost";
  if (!secure) return null;
  try {
    const reg = await navigator.serviceWorker.register("/portal/sw.js", {
      scope: "/portal/",
    });
    await navigator.serviceWorker.ready;
    return reg;
  } catch (err) {
    console.warn("portal SW failed", err);
    return null;
  }
}

export async function enablePortalPush(): Promise<boolean> {
  if (!("Notification" in window) || !("PushManager" in window)) return false;
  if (!window.isSecureContext && location.protocol !== "https:") return false;
  let perm = Notification.permission;
  if (perm === "default") {
    try {
      perm = await Notification.requestPermission();
    } catch {
      return false;
    }
  }
  if (perm !== "granted") return false;
  const reg = await registerPortalSW();
  if (!reg) return false;
  try {
    const { publicKey } = await portalGet<{ publicKey: string }>("/portal/push/vapid-public-key");
    if (!publicKey) return false;
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(publicKey) as BufferSource,
      });
    }
    const json = sub.toJSON();
    await portalPost("/portal/push/subscribe", {
      endpoint: json.endpoint,
      keys: json.keys,
      expirationTime: json.expirationTime ?? null,
    });
    void syncPortalAppBadge();
    return true;
  } catch (err) {
    console.warn("portal push subscribe failed", err);
    return false;
  }
}

async function postToPortalSw(message: object) {
  try {
    const reg = await registerPortalSW();
    const worker = reg?.active || reg?.waiting || reg?.installing;
    worker?.postMessage(message);
  } catch {
    /* ignore */
  }
}

/**
 * Best-practice badge lifecycle (WebKit / MDN):
 * - Set badge from SW on push (authoritative while app closed)
 * - Update from the page when user reads messages
 * - NEVER clearAppBadge on background/blur/pagehide — that wiped the badge
 * - Only clear when unread is known to be 0 while the app is foregrounded
 */
let cachedPortalBadge = 0;
let badgeInitialized = false;

export function getCachedPortalBadgeCount(): number {
  return cachedPortalBadge;
}

function applyBadgeImmediate(count: number, opts?: { allowClear?: boolean }): void {
  const n = Math.max(0, Math.floor(Number(count) || 0));
  if (n <= 0 && !opts?.allowClear) {
    // Refuse to wipe the home-screen badge from an unknown/partial state.
    return;
  }
  cachedPortalBadge = n;
  badgeInitialized = true;
  try {
    const nav = navigator as Navigator & {
      setAppBadge?: (c?: number) => Promise<void>;
      clearAppBadge?: () => Promise<void>;
    };
    if (n > 0 && typeof nav.setAppBadge === "function") {
      void nav.setAppBadge(Math.min(99, n));
    } else if (n <= 0 && typeof nav.clearAppBadge === "function") {
      void nav.clearAppBadge();
    } else if (n <= 0 && typeof nav.setAppBadge === "function") {
      void nav.setAppBadge(0);
    }
  } catch {
    /* ignore */
  }
  if (n > 0) {
    void postToPortalSw({ type: "sk-set-badge", count: n });
  } else if (opts?.allowClear) {
    void postToPortalSw({ type: "sk-clear-badge", allowClear: true });
  }
}

/** On leave: only reinforce a positive badge. Never clear. */
export function persistPortalBadgeNow(): void {
  if (!badgeInitialized) return;
  if (cachedPortalBadge > 0) {
    applyBadgeImmediate(cachedPortalBadge);
  }
}

export async function setPortalAppBadgeCount(count: number): Promise<void> {
  const n = Math.max(0, Math.floor(Number(count) || 0));
  applyBadgeImmediate(n, { allowClear: n === 0 });
}

export async function syncPortalAppBadge(): Promise<number> {
  try {
    const { count } = await portalGet<{ count: number }>("/portal/push/badge");
    const n = Math.max(0, Number(count) || 0);
    applyBadgeImmediate(n, { allowClear: true });
    return n;
  } catch {
    if (badgeInitialized && cachedPortalBadge > 0) {
      applyBadgeImmediate(cachedPortalBadge);
    }
    return cachedPortalBadge;
  }
}

export async function clearPortalAppBadge(): Promise<void> {
  await syncPortalAppBadge();
}

export function bindPortalBadgeLifecycle(): () => void {
  if (typeof window === "undefined") return () => undefined;

  const syncFromServer = () => {
    void syncPortalAppBadge();
  };

  // Reinforce badge when backgrounding — never clear.
  const onHide = () => {
    persistPortalBadgeNow();
  };

  syncFromServer();

  const onVis = () => {
    if (document.visibilityState === "visible") syncFromServer();
    else onHide();
  };

  document.addEventListener("visibilitychange", onVis);
  window.addEventListener("pagehide", onHide);
  // Do NOT listen to `blur` / `focus` spam — Control Center / notif drawer
  // was racing with an uninitialized cache and wiping the badge.
  const onMsg = (event: MessageEvent) => {
    if (event.data?.type === "sk-push-opened") syncFromServer();
  };
  navigator.serviceWorker?.addEventListener?.("message", onMsg as EventListener);

  return () => {
    document.removeEventListener("visibilitychange", onVis);
    window.removeEventListener("pagehide", onHide);
    navigator.serviceWorker?.removeEventListener?.("message", onMsg as EventListener);
  };
}

/** Boot PWA: lock viewport + SW + install capture + optional push after login. */
export function bootPortalPwa(opts?: { requestPush?: boolean }) {
  if (typeof window === "undefined") return () => undefined;
  const standalone = isStandalone();
  document.documentElement.classList.add("p-portal-lock", "p-app-shell");
  document.documentElement.classList.toggle("p-standalone", standalone);
  document.body?.classList.add("p-portal-lock");

  bindInstallPromptCapture();
  void registerPortalSW();

  let cleaned = false;
  let unbindBadge: (() => void) | undefined;
  const wantPush = opts?.requestPush === true;
  const onGesture = () => {
    if (cleaned) return;
    if (wantPush) {
      void enablePortalPush().then((ok) => {
        if (ok && !unbindBadge) unbindBadge = bindPortalBadgeLifecycle();
      });
    }
    window.removeEventListener("pointerdown", onGesture, true);
  };

  if (wantPush && typeof Notification !== "undefined") {
    if (Notification.permission === "default") {
      void enablePortalPush().then((ok) => {
        if (ok && !unbindBadge) unbindBadge = bindPortalBadgeLifecycle();
        if (!ok && Notification.permission === "default") {
          window.addEventListener("pointerdown", onGesture, { once: true, capture: true });
        }
      });
    } else if (Notification.permission === "granted") {
      void enablePortalPush().then((ok) => {
        if (ok && !unbindBadge) unbindBadge = bindPortalBadgeLifecycle();
      });
    }
  }

  try {
    const tab = new URLSearchParams(window.location.search).get("tab");
    if (tab) {
      window.dispatchEvent(new CustomEvent("sk-portal-tab", { detail: tab }));
    }
  } catch {
    /* ignore */
  }

  return () => {
    cleaned = true;
    window.removeEventListener("pointerdown", onGesture, true);
    unbindBadge?.();
  };
}

