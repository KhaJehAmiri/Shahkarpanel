/** One-line credential summary per proxy for admin edit UI. */
export function summarizeProxyCredentials(proxies?: Record<string, unknown> | null): string[] {
  if (!proxies) return [];
  const lines: string[] = [];
  const add = (proto: string, value: string) => {
    if (value) lines.push(`${proto}: ${value}`);
  };
  const mask = (value: string) =>
    value.length <= 10 ? value : `${value.slice(0, 4)}…${value.slice(-4)}`;

  for (const [proto, raw] of Object.entries(proxies)) {
    const s = raw as Record<string, unknown> | undefined;
    if (!s) continue;
    const uuid = s.id ?? s.uuid;
    if (typeof uuid === "string" && uuid) add(proto, `uuid ${uuid}`);
    if (typeof s.password === "string" && s.password) {
      add(proto, `password ${mask(s.password)}`);
    }
    if (typeof s.public_key === "string" && s.public_key) {
      add(proto, `pub ${mask(s.public_key)}`);
    }
    if (typeof s.private_key === "string" && s.private_key) {
      add(proto, `priv ${mask(s.private_key)}`);
    }
    if (typeof s.preshared_key === "string" && s.preshared_key) {
      add(proto, `psk ${mask(s.preshared_key)}`);
    }
    if (typeof s.address === "string" && s.address) add(proto, `ip ${s.address}`);
    if (typeof s.awg_address === "string" && s.awg_address) add(proto, `awg ${s.awg_address}`);
  }
  return lines;
}
