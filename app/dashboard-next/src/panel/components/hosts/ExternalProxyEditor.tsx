"use client";

import { FC, type ChangeEvent } from "react";
import { useTranslation } from "react-i18next";
import { Button, Field, Input, Select } from "../ui";
import { IcPlus, IcTrash } from "../icons";

export type ExternalProxyHop = {
  dest: string;
  port: number | null;
  force_tls: "same" | "tls" | "none";
  sni: string;
  fingerprint: string;
  alpn: string;
  remark: string;
};

export const emptyExternalProxyHop = (): ExternalProxyHop => ({
  dest: "",
  port: 443,
  force_tls: "same",
  sni: "",
  fingerprint: "",
  alpn: "",
  remark: "",
});

export function parseExternalProxyJson(raw: string | undefined): ExternalProxyHop[] {
  const text = (raw || "").trim();
  if (!text) return [];
  try {
    const parsed = JSON.parse(text) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
      .map((item) => ({
        dest: String(item.dest || item.address || ""),
        port: item.port != null && item.port !== "" ? Number(item.port) : null,
        force_tls: (["same", "tls", "none"].includes(String(item.forceTls || item.force_tls))
          ? String(item.forceTls || item.force_tls)
          : "same") as ExternalProxyHop["force_tls"],
        sni: String(item.sni || ""),
        fingerprint: String(item.fingerprint || item.fp || ""),
        alpn: Array.isArray(item.alpn) ? (item.alpn as string[]).join(",") : String(item.alpn || ""),
        remark: String(item.remark || ""),
      }));
  } catch {
    return [];
  }
}

export function serializeExternalProxyJson(hops: ExternalProxyHop[]): string {
  const cleaned = hops
    .filter((h) => h.dest.trim())
    .map((h) => {
      const row: Record<string, unknown> = {
        dest: h.dest.trim(),
        forceTls: h.force_tls,
      };
      if (h.port != null && h.port > 0) row.port = h.port;
      if (h.sni.trim()) row.sni = h.sni.trim();
      if (h.fingerprint.trim()) row.fingerprint = h.fingerprint.trim();
      if (h.alpn.trim()) row.alpn = h.alpn.split(",").map((x) => x.trim()).filter(Boolean);
      if (h.remark.trim()) row.remark = h.remark.trim();
      return row;
    });
  return cleaned.length ? JSON.stringify(cleaned) : "";
}

export const ExternalProxyEditor: FC<{
  value: string;
  onChange: (next: string) => void;
}> = ({ value, onChange }) => {
  const { t } = useTranslation();
  const hops = parseExternalProxyJson(value);

  const setHops = (next: ExternalProxyHop[]) => onChange(serializeExternalProxyJson(next));

  return (
    <div className="sk-stack" style={{ gap: 10 }}>
      <p className="sk-host-ech-hint">{t("infra.hostExternalProxyHint")}</p>
      {hops.map((hop, idx) => (
        <div key={idx} className="sk-card sk-card-pad" style={{ display: "grid", gap: 8 }}>
          <div className="sk-row" style={{ justifyContent: "space-between" }}>
            <strong>{t("infra.hostExternalProxyHop", { n: idx + 1 })}</strong>
            <Button
              size="sm"
              variant="danger"
              onClick={() => setHops(hops.filter((_, i) => i !== idx))}
            >
              <IcTrash className="sk-ico" />
            </Button>
          </div>
          <Field label={t("infra.address")}>
            <Input
              value={hop.dest}
              onChange={(e) => {
                const next = [...hops];
                next[idx] = { ...hop, dest: e.target.value };
                setHops(next);
              }}
              dir="ltr"
            />
          </Field>
          <Field label={t("infra.port")}>
            <Input
              type="number"
              value={hop.port ?? ""}
              onChange={(e) => {
                const next = [...hops];
                next[idx] = {
                  ...hop,
                  port: e.target.value ? parseInt(e.target.value, 10) : null,
                };
                setHops(next);
              }}
              dir="ltr"
            />
          </Field>
          <Field label={t("infra.hostTls")}>
            <Select
              value={hop.force_tls}
              onChange={(e: ChangeEvent<HTMLSelectElement>) => {
                const next = [...hops];
                next[idx] = {
                  ...hop,
                  force_tls: e.target.value as ExternalProxyHop["force_tls"],
                };
                setHops(next);
              }}
            >
              {(["same", "tls", "none"] as const).map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t("infra.hostSni")}>
            <Input
              value={hop.sni}
              onChange={(e) => {
                const next = [...hops];
                next[idx] = { ...hop, sni: e.target.value };
                setHops(next);
              }}
              dir="ltr"
            />
          </Field>
          <Field label={t("infra.hostFp")}>
            <Input
              value={hop.fingerprint}
              onChange={(e) => {
                const next = [...hops];
                next[idx] = { ...hop, fingerprint: e.target.value };
                setHops(next);
              }}
              dir="ltr"
              placeholder="chrome"
            />
          </Field>
          <Field label={t("infra.hostAlpn")}>
            <Input
              value={hop.alpn}
              onChange={(e) => {
                const next = [...hops];
                next[idx] = { ...hop, alpn: e.target.value };
                setHops(next);
              }}
              dir="ltr"
            />
          </Field>
          <Field label={t("infra.hostExternalProxyRemark")}>
            <Input
              value={hop.remark}
              onChange={(e) => {
                const next = [...hops];
                next[idx] = { ...hop, remark: e.target.value };
                setHops(next);
              }}
              dir="ltr"
            />
          </Field>
        </div>
      ))}
      <Button variant="ghost" onClick={() => setHops([...hops, emptyExternalProxyHop()])}>
        <IcPlus className="sk-ico" /> {t("infra.hostExternalProxyAdd")}
      </Button>
    </div>
  );
};
