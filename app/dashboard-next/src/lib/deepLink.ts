const enc = encodeURIComponent;

function withFragment(subUrl: string, name: string): string {
  if (!subUrl) return "";
  if (subUrl.includes("#")) return subUrl;
  return `${subUrl}#${name}`;
}

/** v2rayNG ≥1.8.28 — subscription URL must be fully encoded, name after %23 */
export function v2rayNgSubScheme(subUrl: string, name = "Shahkar"): string {
  return `v2rayng://install-sub/?url=${enc(withFragment(subUrl, name))}`;
}

export function hiddifySubScheme(subUrl: string, name = "Shahkar"): string {
  // Official: hiddify://import/<sub-url>#name — see hiddify.com/app/URL-Scheme/
  const base = subUrl.replace(/#.*$/, "");
  return `hiddify://import/${enc(base)}#${enc(name)}`;
}

export function nekoSubScheme(subUrl: string, name = "Shahkar"): string {
  return `sn://subscription?url=${enc(subUrl.replace(/#.*$/, ""))}&name=${enc(name)}`;
}

export function streisandSubScheme(subUrl: string, name = "Shahkar"): string {
  return `streisand://import/${enc(withFragment(subUrl, name))}`;
}

export function shadowrocketSubScheme(subUrl: string): string {
  const bare = subUrl.replace(/#.*$/, "");
  const b64 =
    typeof btoa !== "undefined" ? btoa(bare) : Buffer.from(bare, "utf-8").toString("base64");
  return `shadowrocket://add/sub://${b64}`;
}

export function v2boxSubScheme(subUrl: string, name = "Shahkar"): string {
  return `v2box://install-sub?url=${enc(subUrl.replace(/#.*$/, ""))}&name=${enc(name)}`;
}

export function clashVergeSubScheme(subUrl: string): string {
  return `clash-verge://install-config?url=${enc(subUrl)}`;
}

/** Open a custom URL scheme from a user gesture (mobile-friendly). */
export function openDeepLink(href: string): void {
  try {
    window.location.assign(href);
  } catch {
    const a = document.createElement("a");
    a.href = href;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }
}
