import { FC, useEffect, useState, type CSSProperties } from "react";
import {
  bytesToDataLimitValue, dataLimitToBytes, detectDataLimitUnit, type DataLimitUnit,
} from "../lib/data-limit";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { InboundsByProtocol } from "../api/types";
import { useFetch } from "../lib/useFetch";
import { formatBytes } from "../lib/format";
import {
  Button, Card, EmptyState, Field, Input, Modal, Select, SkeletonRows, useToast,
} from "./ui";
import { IcPlus, IcTrash, IcEdit } from "./icons";

export interface UserTemplateRow {
  id: number;
  name?: string | null;
  data_limit?: number | null;
  expire_duration?: number | null;
  username_prefix?: string | null;
  username_suffix?: string | null;
  inbounds?: Record<string, string[]>;
}

const PROTO_ORDER = ["vless", "vmess", "trojan", "shadowsocks", "wireguard", "hysteria2", "tuic"];

const NATIVE_PROTOCOLS = ["wireguard", "hysteria2", "tuic"] as const;

const PROTO_VISUAL: Record<string, { icon: string; hue: string; label: string }> = {
  vless: { icon: "⚡", hue: "#2ee0c4", label: "VLESS" },
  vmess: { icon: "◆", hue: "#6366f1", label: "VMess" },
  trojan: { icon: "🔒", hue: "#f59e0b", label: "Trojan" },
  shadowsocks: { icon: "🛡", hue: "#38bdf8", label: "Shadowsocks" },
  wireguard: { icon: "⬡", hue: "#a78bfa", label: "WireGuard" },
  hysteria2: { icon: "🚀", hue: "#f472b6", label: "Hysteria2" },
  tuic: { icon: "◉", hue: "#34d399", label: "TUIC" },
};

export const UserTemplatesPanel: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const [show, setShow] = useState(false);
  const [edit, setEdit] = useState<UserTemplateRow | null>(null);
  const { data, loading, error, reload } = useFetch<UserTemplateRow[]>(() => api.get("/user_template"), []);

  const remove = async (row: UserTemplateRow) => {
    if (!confirm(t("common.confirmDelete"))) return;
    try {
      await api.del(`/user_template/${row.id}`);
      toast.push(t("common.deleted"), "success");
      reload();
    } catch (e: any) {
      toast.push(e.message, "error");
    }
  };

  return (
    <>
      <Card style={{ marginBottom: 16 }}>
        <div className="nx-row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
          <div>
            <b>{t("users.templates")}</b>
            <div className="nx-faint" style={{ fontSize: 12, marginTop: 4 }}>{t("users.templatesDesc")}</div>
          </div>
          <Button variant="primary" size="sm" onClick={() => setShow(true)}><IcPlus className="nx-ico" /> {t("users.addTemplate")}</Button>
        </div>
        {loading ? <SkeletonRows rows={2} cols={3} />
          : error ? <EmptyState title={t("common.error")} desc={error} />
          : !data?.length ? <div className="nx-faint" style={{ fontSize: 13 }}>{t("common.noData")}</div>
          : (
            <div className="nx-table-wrap">
              <table className="nx-table">
                <thead><tr>
                  <th>{t("common.name")}</th><th>{t("users.dataLimit")}</th><th>{t("users.expire")}</th>
                  <th style={{ textAlign: "end" }}>{t("common.actions")}</th>
                </tr></thead>
                <tbody>
                  {data.map((row) => (
                    <tr key={row.id}>
                      <td style={{ fontWeight: 600 }}>{row.name || `#${row.id}`}</td>
                      <td>{row.data_limit ? formatBytes(row.data_limit) : t("users.unlimited")}</td>
                      <td>{row.expire_duration ? `${Math.round(row.expire_duration / 86400)}d` : "—"}</td>
                      <td>
                        <div className="nx-row" style={{ justifyContent: "flex-end", gap: 6 }}>
                          <Button size="sm" variant="ghost" onClick={() => setEdit(row)}><IcEdit className="nx-ico" /></Button>
                          <Button size="sm" variant="danger" onClick={() => remove(row)}><IcTrash className="nx-ico" /></Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </Card>
      {show && <TemplateFormModal onClose={() => setShow(false)} onDone={() => { setShow(false); reload(); }} />}
      {edit && <TemplateFormModal row={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); reload(); }} />}
    </>
  );
};

const TemplateFormModal: FC<{ row?: UserTemplateRow; onClose: () => void; onDone: () => void }> = ({ row, onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const inbounds = useFetch<InboundsByProtocol>(() => api.get("/inbounds"), []);
  const [name, setName] = useState(row?.name || "");
  const [dataLimitUnit, setDataLimitUnit] = useState<DataLimitUnit>(
    row?.data_limit ? detectDataLimitUnit(row.data_limit) : "MB",
  );
  const [dataLimitValue, setDataLimitValue] = useState(
    row?.data_limit ? bytesToDataLimitValue(row.data_limit, detectDataLimitUnit(row.data_limit)) : "",
  );
  const [expireDays, setExpireDays] = useState(row?.expire_duration ? String(Math.round(row.expire_duration / 86400)) : "");
  const [inbSel, setInbSel] = useState<Record<string, string[]>>({});
  const [nativeOn, setNativeOn] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!inbounds.data) return;
    const base = row?.inbounds || {};
    const next: Record<string, string[]> = {};
    Object.keys(inbounds.data).forEach((proto) => {
      const tags = inbounds.data![proto].map((i) => i.tag);
      next[proto] = (base[proto] || []).filter((t) => tags.includes(t));
    });
    setInbSel(next);
    const native: Record<string, boolean> = {};
    NATIVE_PROTOCOLS.forEach((p) => { native[p] = p in base; });
    setNativeOn(native);
  }, [inbounds.data, row?.id]);

  const toggleTag = (proto: string, tag: string) => {
    setInbSel((s) => {
      const cur = s[proto] || [];
      const tags = cur.includes(tag) ? cur.filter((x) => x !== tag) : [...cur, tag];
      return { ...s, [proto]: tags };
    });
  };

  const toggleNative = (proto: string) => {
    setNativeOn((s) => ({ ...s, [proto]: !s[proto] }));
  };

  const submit = async () => {
    setBusy(true);
    try {
      const inboundsBody: Record<string, string[]> = {};
      Object.entries(inbSel).forEach(([proto, tags]) => {
        if (tags.length) inboundsBody[proto] = tags;
      });
      NATIVE_PROTOCOLS.forEach((p) => {
        if (nativeOn[p]) inboundsBody[p] = [];
      });
      const body: Record<string, unknown> = {
        name: name.trim(),
        data_limit: dataLimitValue ? dataLimitToBytes(dataLimitValue, dataLimitUnit) : 0,
        expire_duration: expireDays ? parseInt(expireDays, 10) * 86400 : 0,
        inbounds: inboundsBody,
      };
      if (row) {
        await api.put(`/user_template/${row.id}`, body);
      } else {
        await api.post("/user_template", body);
      }
      toast.push(row ? t("common.saved") : t("common.created"), "success");
      onDone();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const xrayProtos = PROTO_ORDER
    .map((proto) => [proto, inbounds.data?.[proto] || []] as const)
    .filter(([, list]) => list.length > 0);
  const nativeProtos = NATIVE_PROTOCOLS.filter((p) => !inbounds.data?.[p]?.length);

  return (
    <Modal open wide title={row ? t("users.editTemplate") : t("users.addTemplate")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !name.trim()} onClick={submit}>{row ? t("common.save") : t("common.create")}</Button></>}>
      <div className="nx-stack nx-template-form">
        <Field label={t("common.name")}><Input value={name} onChange={(e: any) => setName(e.target.value)} autoFocus /></Field>
        <div className="nx-template-metrics">
          <Field label={t("users.dataLimit")} hint="0 = unlimited">
            <div className="nx-row" style={{ gap: 8 }}>
              <Input type="number" min="0" step={dataLimitUnit === "MB" ? "1" : "0.001"} value={dataLimitValue} onChange={(e: any) => setDataLimitValue(e.target.value)} style={{ flex: 1 }} />
              <Select value={dataLimitUnit} onChange={(e: any) => setDataLimitUnit(e.target.value as DataLimitUnit)} style={{ width: 88 }}>
                <option value="MB">MB</option>
                <option value="GB">GB</option>
              </Select>
            </div>
          </Field>
          <Field label={`${t("users.expire")} (days)`} hint="0 = none"><Input type="number" min="0" value={expireDays} onChange={(e: any) => setExpireDays(e.target.value)} /></Field>
        </div>
        <Field label={t("users.templateInbounds")} hint={t("users.templateInboundsHint")}>
          {inbounds.loading ? <SkeletonRows rows={2} cols={2} /> : (
            <div className="nx-inbound-matrix">
              {xrayProtos.map(([proto, list]) => {
                const vis = PROTO_VISUAL[proto] || { icon: "•", hue: "var(--nx-accent)", label: proto.toUpperCase() };
                return (
                    <div key={proto} className="nx-inbound-matrix-cell" style={{ "--proto-hue": vis.hue } as CSSProperties}>
                    <div className="nx-inbound-matrix-head">
                      <span className="nx-inbound-matrix-icon" aria-hidden>{vis.icon}</span>
                      <span>{vis.label}</span>
                    </div>
                    <div className="nx-inbound-matrix-tags">
                      {list.map((i) => {
                        const active = (inbSel[proto] || []).includes(i.tag);
                        return (
                          <button
                            key={i.tag}
                            type="button"
                            className={`nx-inbound-tag ${active ? "active" : ""}`}
                            onClick={() => toggleTag(proto, i.tag)}
                          >
                            <span className="nx-inbound-tag-check" aria-hidden>{active ? "✓" : ""}</span>
                            {i.tag}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
              {nativeProtos.map((proto) => {
                const vis = PROTO_VISUAL[proto] || { icon: "•", hue: "var(--nx-accent)", label: proto.toUpperCase() };
                const active = !!nativeOn[proto];
                return (
                  <div key={proto} className="nx-inbound-matrix-cell" style={{ "--proto-hue": vis.hue } as CSSProperties}>
                    <div className="nx-inbound-matrix-head">
                      <span className="nx-inbound-matrix-icon" aria-hidden>{vis.icon}</span>
                      <span>{vis.label}</span>
                    </div>
                    <div className="nx-inbound-matrix-tags">
                      <button
                        type="button"
                        className={`nx-inbound-tag ${active ? "active" : ""}`}
                        onClick={() => toggleNative(proto)}
                      >
                        <span className="nx-inbound-tag-check" aria-hidden>{active ? "✓" : ""}</span>
                        {t("users.wgNativePeer")}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Field>
      </div>
    </Modal>
  );
};
