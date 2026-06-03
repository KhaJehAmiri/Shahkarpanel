import { ChangeEvent, FC } from "react";
import { useTranslation } from "react-i18next";
import { Button, Callout, Card, Field, Input } from "../ui";

export const DnsSection: FC<{
  config: Record<string, unknown>;
  onChange: (c: Record<string, unknown>) => void;
  onSave: () => void;
  saving: boolean;
}> = ({ config, onChange, onSave, saving }) => {
  const { t } = useTranslation();
  const dns = (config.dns || { servers: [] }) as Record<string, unknown>;
  const servers = Array.isArray(dns.servers) ? (dns.servers as unknown[]).map(String) : [];
  const text = servers.join("\n");

  const setServers = (raw: string) => {
    const list = raw.split("\n").map((s) => s.trim()).filter(Boolean);
    onChange({ ...config, dns: { ...dns, servers: list } });
  };

  return (
    <div className="nx-stack">
      <Callout tone="info" title={t("xray.dnsTitle")}>{t("xray.dnsDesc")}</Callout>
      <Card>
        <Field label={t("xray.dnsServers")}>
          <textarea
            className="nx-input"
            rows={6}
            value={text}
            onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setServers(e.target.value)}
            placeholder={"1.1.1.1\n8.8.8.8\nhttps://dns.google/dns-query"}
            style={{ fontFamily: "var(--nx-font-mono)", fontSize: 12 }}
          />
        </Field>
        <Field label={`${t("xray.dnsQueryStrategy")} (${t("common.optional")})`}>
          <Input
            value={String(dns.queryStrategy || "")}
            onChange={(e) => onChange({ ...config, dns: { ...dns, queryStrategy: e.target.value || undefined } })}
            placeholder="UseIP / UseIPv4"
          />
        </Field>
      </Card>
      <div className="nx-row" style={{ justifyContent: "flex-end" }}>
        <Button variant="primary" disabled={saving} onClick={onSave}>{t("common.save")}</Button>
      </div>
    </div>
  );
};
