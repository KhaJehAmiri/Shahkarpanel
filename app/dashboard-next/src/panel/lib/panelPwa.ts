/** Panel (admin / reseller) PWA install helpers */

const DISMISS_INSTALL_SESSION = "nx_panel_install_skip_session";

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

let deferredInstall: BeforeInstallPromptEvent | null = null;
let installListenerBound = false;

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

/** Phone/tablet only — never show install UX on desktop Windows/macOS. */
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
  window.dispatchEvent(new CustomEvent("sk-panel-install-dismissed"));
}

/** Capture Chrome/Edge/Android system install prompt as early as possible. */
export function bindInstallPromptCapture() {
  if (typeof window === "undefined" || installListenerBound) return;
  installListenerBound = true;

  if (!isMobileDevice()) return;

  const w = window as Window & { __nxPanelBip?: BeforeInstallPromptEvent };
  if (w.__nxPanelBip) {
    deferredInstall = w.__nxPanelBip;
    w.__nxPanelBip = undefined;
    queueMicrotask(() => window.dispatchEvent(new CustomEvent("sk-panel-install-ready")));
  }

  window.addEventListener("beforeinstallprompt", (e) => {
    if (!isMobileDevice()) return;
    e.preventDefault();
    deferredInstall = e as BeforeInstallPromptEvent;
    w.__nxPanelBip = undefined;
    window.dispatchEvent(new CustomEvent("sk-panel-install-ready"));
  });

  window.addEventListener("appinstalled", () => {
    deferredInstall = null;
    try {
      sessionStorage.setItem(DISMISS_INSTALL_SESSION, "1");
    } catch {
      /* ignore */
    }
    window.dispatchEvent(new CustomEvent("sk-panel-installed"));
  });
}

export async function promptPanelInstall(): Promise<"accepted" | "dismissed" | "unavailable"> {
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
    console.warn("panel install prompt failed", err);
    return "unavailable";
  }
}

export async function registerPanelSW(): Promise<ServiceWorkerRegistration | null> {
  if (!("serviceWorker" in navigator)) return null;
  const secure =
    window.isSecureContext ||
    location.protocol === "https:" ||
    location.hostname === "localhost";
  if (!secure) return null;
  try {
    const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
    await navigator.serviceWorker.ready;
    return reg;
  } catch (err) {
    console.warn("panel SW failed", err);
    return null;
  }
}

/** Boot panel PWA: SW + install capture + standalone class. */
export function bootPanelPwa() {
  if (typeof window === "undefined") return () => undefined;

  const applyStandalone = () => {
    document.documentElement.classList.toggle("sk-standalone", isStandalone());
  };
  applyStandalone();

  bindInstallPromptCapture();
  void registerPanelSW();

  const mq = window.matchMedia("(display-mode: standalone)");
  mq.addEventListener?.("change", applyStandalone);
  return () => mq.removeEventListener?.("change", applyStandalone);
}
