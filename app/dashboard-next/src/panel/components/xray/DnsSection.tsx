import { ChangeEvent, FC } from "react";
import { useTranslation } from "react-i18next";
import { Button, Callout, Card, Checkbox, Field, Input } from "../ui";

function stringifyHosts(hosts: unknown): string {
  if (!hosts || typeof hosts !== "object") return "";
  return Object.entries(hosts as Record<string, unknown>)
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? (v as unknown[]).map(String).join(", ") : String(v)}`)
    .join("\n");
}

function parseHosts(raw: string): Record<string, unknown> | undefined {
  const out: Record<string, unknown> = {};
  for (const line of raw.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const sep = trimmed.indexOf(":") >= 0 ? ":" : trimmed.indexOf("=") >= 0 ? "=" : "";
    if (!sep) continue;
    const idx = trimmed.indexOf(sep);
    const key = trimmed.slice(0, idx).trim();
    const valRaw = trimmed.slice(idx + 1).trim();
    if (!key) continue;
    const vals = valRaw.split(",").map((s) => s.trim()).filter(Boolean);
    out[key] = vals.length <= 1 ? (vals[0] ?? "") : vals;
  }
  return Object.keys(out).length ? out : undefined;
}

export const DnsSection: FC<{
  config: Record<string, unknown>;
  onChange: (c: Record<string, unknown>) => void;
  onSave: () => void;
  saving: boolean;
}> = ({ config, onChange, onSave, saving }) => {
  const { t } = useTranslation();
  const dns = (config.dns || { servers: [] }) as Record<string, unknown>;
  const rawServers = Array.isArray(dns.servers) ? (dns.servers as unknown[]) : [];

  // Preserve object-form (advanced) servers; only the plain-string ones are textarea-editable.
  const stringServers = rawServers.filter((s) => typeof s === "string").map(String);
  const objectServers = rawServers.filter((s) => typeof s === "object" && s !== null);
  const text = stringServers.join("\n");

  const patchDns = (patch: Record<string, unknown>) => {
    onChange({ ...config, dns: { ...dns, ...patch } });
  };

  const setServers = (raw: string) => {
    const list = raw.split("\n").map((s) => s.trim()).filter(Boolean);
    patchDns({ servers: [...list, ...objectServers] });
  };

  return (
    <div className="sk-stack">
      <Callout tone="info" title={t("xray.dnsTitle")}>{t("xray.dnsDesc")}</Callout>
      <Card>
        <Field label={t("xray.dnsServers")}>
          <textarea
            className="sk-input"
            rows={6}
            value={text}
            onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setServers(e.target.value)}
            placeholder={"1.1.1.1\n8.8.8.8\nhttps://dns.google/dns-query"}
            style={{ fontFamily: "var(--sk-font-mono)", fontSize: 12 }}
          />
        </Field>
        {objectServers.length > 0 && (
          <Callout tone="info" title={t("xray.dnsAdvancedServers")}>
            {t("xray.dnsAdvancedServersHint", { count: objectServers.length })}
          </Callout>
        )}
        <Field label={t("xray.dnsHosts")} hint={t("xray.dnsHostsHint")}>
          <textarea
            className="sk-input"
            rows={4}
            value={stringifyHosts(dns.hosts)}
            onChange={(e: ChangeEvent<HTMLTextAreaElement>) => patchDns({ hosts: parseHosts(e.target.value) })}
            placeholder={"domain.com: 1.2.3.4\ngeosite:category-ads-all: 127.0.0.1"}
            style={{ fontFamily: "var(--sk-font-mono)", fontSize: 12 }}
          />
        </Field>
        <div className="sk-row" style={{ gap: 12, flexWrap: "wrap" }}>
          <Field label={`${t("xray.dnsClientIp")} (${t("common.optional")})`}>
            <Input
              value={String(dns.clientIp || "")}
              onChange={(e) => patchDns({ clientIp: e.target.value || undefined })}
              placeholder="1.2.3.4"
            />
          </Field>
          <Field label={`${t("xray.dnsQueryStrategy")} (${t("common.optional")})`}>
            <Input
              value={String(dns.queryStrategy || "")}
              onChange={(e) => patchDns({ queryStrategy: e.target.value || undefined })}
              placeholder="UseIP / UseIPv4"
            />
          </Field>
          <Field label={`${t("xray.dnsTag")} (${t("common.optional")})`}>
            <Input
              value={String(dns.tag || "")}
              onChange={(e) => patchDns({ tag: e.target.value || undefined })}
              placeholder="dns-out"
            />
          </Field>
        </div>
        <label className="sk-row" style={{ gap: 8, cursor: "pointer" }}>
          <Checkbox checked={Boolean(dns.disableCache)} onChange={() => patchDns({ disableCache: !dns.disableCache })} />
          <span>{t("xray.dnsDisableCache")}</span>
        </label>
        <label className="sk-row" style={{ gap: 8, cursor: "pointer", marginTop: 8 }}>
          <Checkbox
            checked={Boolean((dns.fakeDns as Record<string, unknown> | undefined)?.enabled)}
            onChange={() => {
              const fake = (dns.fakeDns as Record<string, unknown> | undefined) || {};
              patchDns({ fakeDns: { ...fake, enabled: !fake.enabled } });
            }}
          />
          <span>{t("xray.dnsFakeDns", "Enable fake DNS")}</span>
        </label>
        <Field label={t("xray.dnsSplitServers", "Split-horizon servers (JSON)")} hint={t("xray.dnsSplitHint", "Optional per-domain DNS servers as JSON array.")}>
          <textarea
            className="sk-input"
            rows={4}
            value={typeof dns.servers === "object" ? JSON.stringify(dns.servers, null, 2) : text}
            onChange={(e: ChangeEvent<HTMLTextAreaElement>) => {
              try {
                const parsed = JSON.parse(e.target.value);
                if (Array.isArray(parsed)) patchDns({ servers: parsed });
              } catch {
                setServers(e.target.value);
              }
            }}
            style={{ fontFamily: "var(--sk-font-mono)", fontSize: 12 }}
          />
        </Field>
      </Card>
      <div className="sk-row" style={{ justifyContent: "flex-end" }}>
        <Button variant="primary" disabled={saving} onClick={onSave}>{t("common.save")}</Button>
      </div>
    </div>
  );
};
