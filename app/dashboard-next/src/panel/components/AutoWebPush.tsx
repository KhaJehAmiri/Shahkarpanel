import { FC, useEffect } from "react";
import {
  bindAdminBadgeLifecycle,
  ensureServiceWorker,
  pushSupported,
  requestPushPermissionAndSubscribe,
  subscribeWebPush,
  wasPushAsked,
} from "../lib/webPush";

/**
 * Invisible bootstrap: when the panel opens (or on first tap if the browser
 * blocks auto-prompts), show the native notification permission dialog — no button.
 * Also keeps the home-screen app badge synced (Telegram-style).
 */
export const AutoWebPush: FC = () => {
  useEffect(() => {
    if (!pushSupported()) return;

    let cancelled = false;
    let interactionBound = false;
    let unbindBadge: (() => void) | undefined;

    const run = async (fromGesture: boolean) => {
      if (cancelled) return;
      if (Notification.permission === "granted") {
        try {
          await subscribeWebPush();
          if (!cancelled && !unbindBadge) unbindBadge = bindAdminBadgeLifecycle();
        } catch {
          /* ignore */
        }
        return;
      }
      if (Notification.permission === "denied") return;

      if (!fromGesture && wasPushAsked()) return;

      const result = await requestPushPermissionAndSubscribe();
      if (result === "granted" && !cancelled && !unbindBadge) {
        unbindBadge = bindAdminBadgeLifecycle();
      }
      if (result === "default" && !fromGesture && !interactionBound) {
        bindFirstGesture();
      }
    };

    const onFirstGesture = () => {
      unbindFirstGesture();
      void run(true);
    };

    const bindFirstGesture = () => {
      if (interactionBound) return;
      interactionBound = true;
      window.addEventListener("pointerdown", onFirstGesture, { once: true, capture: true });
      window.addEventListener("keydown", onFirstGesture, { once: true, capture: true });
    };

    const unbindFirstGesture = () => {
      interactionBound = false;
      window.removeEventListener("pointerdown", onFirstGesture, true);
      window.removeEventListener("keydown", onFirstGesture, true);
    };

    void ensureServiceWorker();
    const t = window.setTimeout(() => {
      void run(false).then(() => {
        if (!cancelled && Notification.permission === "default") {
          bindFirstGesture();
        }
      });
    }, 600);

    return () => {
      cancelled = true;
      window.clearTimeout(t);
      unbindFirstGesture();
      unbindBadge?.();
    };
  }, []);

  return null;
};
