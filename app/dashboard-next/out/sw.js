/* Shahkar admin / reseller service worker — PWA + Web Push + app icon badge */
const CACHE = "sk-shell-v4";
const PUSH_META = "sk-push-meta-v1";
const PRECACHE = [
  "/brand/pwa-192.png",
  "/brand/pwa-512.png",
  "/brand/favicon-48.png",
  "/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(PRECACHE).catch(() => undefined)),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter((k) => k.startsWith("sk-shell-") && k !== CACHE)
          .map((k) => caches.delete(k)),
      );
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  let url;
  try {
    url = new URL(req.url);
  } catch (_) {
    return;
  }
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;

  // Never intercept navigations with a JSON/manifest fallback — that breaks the panel UI.
  const isNavigate =
    req.mode === "navigate" ||
    req.destination === "document" ||
    (req.headers.get("accept") || "").includes("text/html");
  if (isNavigate) {
    event.respondWith(fetch(req));
    return;
  }

  // Immutable hashed assets + brand icons: cache-first.
  const cacheFirst =
    url.pathname.startsWith("/_next/static/") ||
    url.pathname.startsWith("/fonts/") ||
    url.pathname.startsWith("/brand/");

  if (cacheFirst) {
    event.respondWith(
      caches.open(CACHE).then(async (cache) => {
        const hit = await cache.match(req);
        if (hit) return hit;
        const res = await fetch(req);
        if (res && res.ok) {
          try {
            cache.put(req, res.clone());
          } catch (_) {}
        }
        return res;
      }),
    );
    return;
  }

  // Default: network only (no manifest / HTML fallback).
  event.respondWith(fetch(req));
});

async function applyAppBadge(count) {
  try {
    if (typeof self.registration.setAppBadge !== "function") return;
    const n = Number(count);
    if (Number.isFinite(n) && n > 0) {
      await self.registration.setAppBadge(Math.min(99, Math.floor(n)));
    } else if (typeof self.registration.clearAppBadge === "function") {
      await self.registration.clearAppBadge();
    } else if (typeof self.registration.setAppBadge === "function") {
      await self.registration.setAppBadge(0);
    }
  } catch (_) {
    /* unsupported */
  }
}

self.addEventListener("push", (event) => {
  let data = {
    title: "Shahkar",
    body: "",
    url: "__DASHBOARD_PATH__#/billing",
    tag: "sk-push",
    count: 1,
  };
  try {
    if (event.data) {
      const parsed = event.data.json();
      data = { ...data, ...parsed };
    }
  } catch (_) {
    try {
      data.body = event.data ? event.data.text() : "";
    } catch (__) {
      /* ignore */
    }
  }
  const dash = "__DASHBOARD_PATH__";
  const count = data.count != null ? data.count : data.badgeCount != null ? data.badgeCount : 1;
  const targetUrl = data.url || `${dash}#/billing`;

  // Same pattern as portal: badge + visible system notification together.
  event.waitUntil(
    Promise.all([
      applyAppBadge(count),
      self.registration.showNotification(data.title || "Shahkar", {
        body: data.body || "",
        icon: "/brand/pwa-192.png",
        badge: "/brand/favicon-48.png",
        tag: data.tag || "sk-push",
        renotify: true,
        requireInteraction: true,
        vibrate: [120, 60, 120],
        data: {
          url: targetUrl,
          count,
        },
      }),
    ]),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target =
    (event.notification.data && event.notification.data.url) ||
    "__DASHBOARD_PATH__#/billing";
  const count = event.notification.data && event.notification.data.count;
  event.waitUntil(
    (async () => {
      // Do NOT wipe badge on click — only sync from in-app attention count.
      if (count != null && Number(count) > 0) await applyAppBadge(count);
      const list = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const client of list) {
        if ("focus" in client) {
          try {
            client.postMessage({ type: "sk-push-opened", url: target });
          } catch (_) {}
          if ("navigate" in client) {
            try {
              await client.navigate(target);
            } catch (_) {}
          }
          return client.focus();
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow(target);
    })(),
  );
});

self.addEventListener("message", (event) => {
  const msg = event.data || {};
  if (msg.type === "sk-set-badge") {
    const n = Number(msg.count);
    if (!Number.isFinite(n)) return;
    // Ignore accidental clears from an uninitialized client.
    if (n <= 0 && msg.allowClear !== true) return;
    event.waitUntil(applyAppBadge(n));
  } else if (msg.type === "sk-clear-badge" && msg.allowClear === true) {
    event.waitUntil(applyAppBadge(0));
  } else if (msg.type === "sk-push-meta" && msg.meta) {
    event.waitUntil(
      caches.open(PUSH_META).then((cache) =>
        cache.put(
          "/meta",
          new Response(JSON.stringify(msg.meta), {
            headers: { "Content-Type": "application/json" },
          }),
        ),
      ),
    );
  }
});

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

/** Browser rotated the push endpoint while the panel was closed — re-register. */
self.addEventListener("pushsubscriptionchange", (event) => {
  event.waitUntil(
    (async () => {
      const clients = await self.clients.matchAll({
        type: "window",
        includeUncontrolled: true,
      });
      for (const client of clients) {
        try {
          client.postMessage({ type: "sk-push-resubscribe" });
        } catch (_) {}
      }

      let meta = null;
      try {
        const cache = await caches.open(PUSH_META);
        const res = await cache.match("/meta");
        if (res) meta = await res.json();
      } catch (_) {}
      if (!meta || !meta.vapidPublicKey || !meta.accessToken || !meta.apiBase) return;

      try {
        const sub = await self.registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(meta.vapidPublicKey),
        });
        const json = sub.toJSON();
        if (!json.endpoint || !json.keys || !json.keys.p256dh || !json.keys.auth) return;
        const base = String(meta.apiBase).replace(/\/?$/, "/");
        await fetch(`${base}push/subscribe`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${meta.accessToken}`,
          },
          body: JSON.stringify({
            endpoint: json.endpoint,
            keys: json.keys,
            expirationTime: json.expirationTime ?? null,
          }),
        });
      } catch (_) {
        /* open panel later will re-subscribe */
      }
    })(),
  );
});
