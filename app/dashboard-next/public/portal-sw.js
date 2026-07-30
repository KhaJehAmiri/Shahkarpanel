/* Shahkar Portal PWA — installable user app + push + app icon badge
 *
 * iOS Badging (WebKit): use self.navigator.setAppBadge inside push waitUntil
 * together with showNotification. Never clearAppBadge on app background.
 */
const CACHE = "sk-portal-v1";
const PRECACHE = ["/portal/", "/portal/manifest.webmanifest", "/brand/pwa-192.png", "/brand/pwa-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE).catch(() => undefined)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys.filter((k) => k.startsWith("sk-portal-") && k !== CACHE).map((k) => caches.delete(k)),
      );
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.pathname.startsWith("/api/")) return;

  // Immutable hashed assets + fonts: cache-first (big win on slow networks).
  const cacheFirst =
    url.pathname.startsWith("/_next/static/") ||
    url.pathname.startsWith("/fonts/") ||
    url.pathname.startsWith("/brand/");

  if (cacheFirst) {
    event.respondWith(
      caches.open(CACHE).then(async (cache) => {
        const hit = await cache.match(req);
        if (hit) return hit;
        try {
          const res = await fetch(req);
          if (res && res.ok) {
            try {
              cache.put(req, res.clone());
            } catch (_) {}
          }
          return res;
        } catch (_) {
          return hit || Response.error();
        }
      }),
    );
    return;
  }

  // HTML / portal shell: network-first, cache fallback.
  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res && res.ok && url.pathname.startsWith("/portal")) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => undefined);
        }
        return res;
      })
      .catch(() => caches.match(req).then((hit) => hit || caches.match("/portal/"))),
  );
});

/** WebKit recommends navigator.setAppBadge in the service worker. */
async function applyAppBadge(count) {
  const n = Number(count);
  const value = Number.isFinite(n) && n > 0 ? Math.min(99, Math.floor(n)) : 0;
  try {
    const nav = self.navigator;
    if (nav && typeof nav.setAppBadge === "function") {
      if (value > 0) await nav.setAppBadge(value);
      else if (typeof nav.clearAppBadge === "function") await nav.clearAppBadge();
      else await nav.setAppBadge(0);
      return;
    }
  } catch (_) {}
  try {
    if (typeof self.registration.setAppBadge === "function") {
      if (value > 0) await self.registration.setAppBadge(value);
      else if (typeof self.registration.clearAppBadge === "function") {
        await self.registration.clearAppBadge();
      }
    }
  } catch (_) {}
}

self.addEventListener("push", (event) => {
  let data = {
    title: "Shahkar",
    body: "",
    url: "/portal/?tab=history",
    tag: "portal",
    count: 1,
  };
  try {
    if (event.data) data = { ...data, ...event.data.json() };
  } catch (_) {
    try {
      data.body = event.data ? event.data.text() : "";
    } catch (__) {}
  }
  const count = data.count != null ? data.count : data.badgeCount != null ? data.badgeCount : 1;

  // Official pattern: badge + visible notification inside the same waitUntil.
  event.waitUntil(
    Promise.all([
      applyAppBadge(count),
      self.registration.showNotification(data.title || "Shahkar", {
        body: data.body || "",
        icon: "/brand/pwa-192.png",
        badge: "/brand/favicon-48.png",
        tag: data.tag || "portal",
        renotify: true,
        requireInteraction: true,
        vibrate: [120, 60, 120],
        data: { url: data.url || "/portal/?tab=history", count },
      }),
    ]),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/portal/?tab=history";
  const count = event.notification.data && event.notification.data.count;
  event.waitUntil(
    (async () => {
      // Do NOT clear badge on click — only when user marks messages read in-app.
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
    // Ignore accidental clears from an uninitialized client.
    if (!Number.isFinite(n)) return;
    if (n <= 0 && msg.allowClear !== true) return;
    event.waitUntil(applyAppBadge(n));
  } else if (msg.type === "sk-clear-badge" && msg.allowClear === true) {
    event.waitUntil(applyAppBadge(0));
  }
});
