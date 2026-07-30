import { FC, useEffect, useState, type CSSProperties } from "react";
import {
  bytesToDataLimitValue, dataLimitToBytes, detectDataLimitUnit, type DataLimitUnit,
} from "../lib/data-limit";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { InboundsByProtocol, NodeItem } from "../api/types";
import { useFetch } from "../lib/useFetch";
import { type AssignableNativeProtocols, protocolAssignable } from "../lib/userHelpers";
import { formatBytes } from "../lib/format";
import {
  Button, Card, EmptyState, Field, Input, Modal, Select, SkeletonRows, useToast,
} from "./ui";
import { IcPlus, IcTrash, IcEdit } from "./icons";
import { TableRowMenu } from "./TableRowMenu";

export interface UserTemplateRow {
  id: number;
  name?: string | null;
  data_limit?: number | null;
  expire_duration?: number | null;
  username_prefix?: string | null;
  username_suffix?: string | null;
  inbounds?: Record<string, string[]>;
  data_limit_reset_strategy?: string | null;
  default_status?: string | null;
  note?: string | null;
  next_plan?: {
    data_limit?: number | null;
    expire?: number | null;
    add_remaining_traffic?: boolean;
    fire_on_either?: boolean;
  } | null;
}

const PROTO_ORDER = ["vless", "vmess", "trojan", "shadowsocks", "wireguard", "amneziawg", "hysteria2", "tuic", "anytls"];

const NATIVE_PROTOCOLS = ["wireguard", "amneziawg", "hysteria2", "tuic", "anytls"] as const;

const PROTO_VISUAL: Record<string, { icon: string; hue: string; label: string }> = {
  vless: { icon: "VL", hue: "#2ee0c4", label: "VLESS" },
  vmess: { icon: "VM", hue: "#818cf8", label: "VMess" },
  trojan: { icon: "TR", hue: "#f59e0b", label: "Trojan" },
  shadowsocks: { icon: "SS", hue: "#38bdf8", label: "Shadowsocks" },
  wireguard: { icon: "WG", hue: "#94a3b8", label: "WireGuard" },
  amneziawg: { icon: "AW", hue: "#22d3ee", label: "AmneziaWG" },
  hysteria2: { icon: "H2", hue: "#f472b6", label: "Hysteria2" },
  tuic: { icon: "TU", hue: "#34d399", label: "TUIC" },
  anytls: { icon: "AT", hue: "#a78bfa", label: "AnyTLS" },
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
      <Card className="sk-mb-20 sk-templates-card">
        <div className="sk-templates-bar">
          <div className="sk-templates-bar-text">
            <span className="sk-templates-bar-title">{t("users.templates")}</span>
            <span className="sk-templates-bar-desc">{t("users.templatesDesc")}</span>
          </div>
          <Button variant="primary" size="sm" onClick={() => setShow(true)}>
            <IcPlus className="sk-ico" /> {t("users.addTemplate")}
          </Button>
        </div>
        {loading && !data ? (
          <div style={{ marginTop: 12 }}><SkeletonRows rows={2} cols={3} /></div>
        ) : error && !data ? (
          <EmptyState title={t("common.error")} desc={error} />
        ) : data && data.length > 0 ? (
          <div className="sk-table-wrap sk-templates-table">
            <table className="sk-table">
              <thead>
                <tr>
                  <th>{t("common.name")}</th>
                  <th>{t("users.dataLimit")}</th>
                  <th>{t("users.expire")}</th>
                  <th className="sk-actions" />
                </tr>
              </thead>
              <tbody>
                {data.map((row) => (
                  <tr key={row.id}>
                    <td><span className="sk-proto-name-main">{row.name || `#${row.id}`}</span></td>
                    <td className="sk-proto-meta">{row.data_limit ? formatBytes(row.data_limit) : t("users.unlimited")}</td>
                    <td className="sk-proto-meta">{row.expire_duration ? `${Math.round(row.expire_duration / 86400)}d` : "—"}</td>
                    <td className="sk-actions">
                      <TableRowMenu
                        items={[
                          {
                            id: "edit",
                            label: t("common.edit"),
                            icon: <IcEdit className="sk-ico" />,
                            onClick: () => setEdit(row),
                          },
                          {
                            id: "del",
                            label: t("common.delete"),
                            icon: <IcTrash className="sk-ico" />,
                            danger: true,
                            onClick: () => remove(row),
                          },
                        ]}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
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
  const nodes = useFetch<NodeItem[]>(() => api.get("/nodes"), []);
  const nativeCaps = useFetch<AssignableNativeProtocols>(
    () => api.get("/assignable-native-protocols"),
    [],
  );
  const [name, setName] = useState(row?.name || "");
  const [dataLimitUnit, setDataLimitUnit] = useState<DataLimitUnit>(
    row?.data_limit ? detectDataLimitUnit(row.data_limit) : "MB",
  );
  const [dataLimitValue, setDataLimitValue] = useState(
    row?.data_limit ? bytesToDataLimitValue(row.data_limit, detectDataLimitUnit(row.data_limit)) : "",
  );
  const [expireDays, setExpireDays] = useState(row?.expire_duration ? String(Math.round(row.expire_duration / 86400)) : "");
  const [resetStrategy, setResetStrategy] = useState(row?.data_limit_reset_strategy || "no_reset");
  const [defaultStatus, setDefaultStatus] = useState(row?.default_status || "active");
  const [note, setNote] = useState(row?.note || "");
  const [nextPlanEnabled, setNextPlanEnabled] = useState(!!row?.next_plan);
  const [nextDataLimit, setNextDataLimit] = useState(row?.next_plan?.data_limit ? String(row.next_plan.data_limit) : "");
  const [nextExpireDays, setNextExpireDays] = useState(
    row?.next_plan?.expire ? String(Math.round(row.next_plan.expire / 86400)) : "",
  );
  const [nextAddRemaining, setNextAddRemaining] = useState(!!row?.next_plan?.add_remaining_traffic);
  const [nextFireEither, setNextFireEither] = useState(row?.next_plan?.fire_on_either !== false);
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
        if (p === "wireguard" || p === "amneziawg") return;
        if (nativeOn[p]) inboundsBody[p] = [];
      });
      if (nativeOn.wireguard && nativeOn.amneziawg) {
        inboundsBody.wireguard = ["__native:wireguard", "__native:amneziawg"];
      } else if (nativeOn.amneziawg) {
        inboundsBody.wireguard = ["__native:amneziawg"];
      } else if (nativeOn.wireguard) {
        inboundsBody.wireguard = ["__native:wireguard"];
      }
      const body: Record<string, unknown> = {
        name: name.trim(),
        data_limit: dataLimitValue ? dataLimitToBytes(dataLimitValue, dataLimitUnit) : 0,
        expire_duration: expireDays ? parseInt(expireDays, 10) * 86400 : 0,
        inbounds: inboundsBody,
        data_limit_reset_strategy: resetStrategy,
        default_status: defaultStatus,
        note: note.trim() || null,
      };
      if (nextPlanEnabled) {
        body.next_plan = {
          data_limit: nextDataLimit ? parseInt(nextDataLimit, 10) : 0,
          expire: nextExpireDays ? parseInt(nextExpireDays, 10) * 86400 : 0,
          add_remaining_traffic: nextAddRemaining,
          fire_on_either: nextFireEither,
        };
      } else if (row?.next_plan) {
        body.next_plan = null;
      }
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
  const nativeProtos = NATIVE_PROTOCOLS.filter((p) => {
    if ((inbounds.data?.[p]?.length || 0) > 0) return false;
    return protocolAssignable(
      p,
      inbounds.data ?? undefined,
      nodes.data ?? undefined,
      nativeCaps.data,
    );
  });

  return (
    <Modal
      open
      formWide
      className="sk-uc-template-shell"
      title={row ? t("users.editTemplate") : t("users.addTemplate")}
      subtitle={t("users.templatesDesc")}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="primary" disabled={busy || !name.trim()} onClick={submit}>
            {row ? t("common.save") : t("common.create")}
          </Button>
        </>
      }
    >
      <div className="sk-stack sk-template-form">
        <Field label={t("common.name")}><Input value={name} onChange={(e: any) => setName(e.target.value)} autoFocus /></Field>
        <div className="sk-template-metrics">
          <Field label={t("users.dataLimit")} hint="0 = unlimited">
            <div className="sk-row" style={{ gap: 8 }}>
              <Input type="number" min="0" step={dataLimitUnit === "MB" ? "1" : "0.001"} value={dataLimitValue} onChange={(e: any) => setDataLimitValue(e.target.value)} style={{ flex: 1 }} />
              <Select value={dataLimitUnit} onChange={(e: any) => setDataLimitUnit(e.target.value as DataLimitUnit)} style={{ width: 88 }}>
                <option value="MB">MB</option>
                <option value="GB">GB</option>
              </Select>
            </div>
          </Field>
          <Field label={`${t("users.expire")} (days)`} hint="0 = none"><Input type="number" min="0" value={expireDays} onChange={(e: any) => setExpireDays(e.target.value)} /></Field>
        </div>
        <div className="sk-template-metrics">
          <Field label={t("users.resetStrategy")}>
            <Select value={resetStrategy} onChange={(e: any) => setResetStrategy(e.target.value)}>
              {["no_reset", "day", "week", "month", "year"].map((r) => (
                <option key={r} value={r}>{t(`users.resetStrategies.${r}`, r)}</option>
              ))}
            </Select>
          </Field>
          <Field label={t("users.templateDefaultStatus", { defaultValue: "Default status" })}>
            <Select value={defaultStatus} onChange={(e: any) => setDefaultStatus(e.target.value)}>
              <option value="active">{t("users.status.active")}</option>
              <option value="on_hold">{t("users.status.on_hold")}</option>
            </Select>
          </Field>
        </div>
        <Field label={`${t("users.noteLabel")} (${t("common.optional")})`}>
          <Input value={note} onChange={(e: any) => setNote(e.target.value)} />
        </Field>
        <Card style={{ padding: 14 }}>
          <label className="sk-row" style={{ gap: 8, marginBottom: 10 }}>
            <input type="checkbox" checked={nextPlanEnabled} onChange={(e) => setNextPlanEnabled(e.target.checked)} />
            {t("users.nextPlan", { defaultValue: "Next plan (renewal)" })}
          </label>
          {nextPlanEnabled && (
            <div className="sk-template-metrics">
              <Field label={t("users.dataLimit")}>
                <Input type="number" min="0" value={nextDataLimit} onChange={(e: any) => setNextDataLimit(e.target.value)} />
              </Field>
              <Field label={`${t("users.expire")} (days)`}>
                <Input type="number" min="0" value={nextExpireDays} onChange={(e: any) => setNextExpireDays(e.target.value)} />
              </Field>
              <label className="sk-row" style={{ gap: 8, fontSize: 12 }}>
                <input type="checkbox" checked={nextAddRemaining} onChange={(e) => setNextAddRemaining(e.target.checked)} />
                {t("users.nextAddRemaining", { defaultValue: "Add remaining traffic" })}
              </label>
              <label className="sk-row" style={{ gap: 8, fontSize: 12 }}>
                <input type="checkbox" checked={nextFireEither} onChange={(e) => setNextFireEither(e.target.checked)} />
                {t("users.nextFireEither", { defaultValue: "Fire on either limit" })}
              </label>
            </div>
          )}
        </Card>
        <Field label={t("users.templateInbounds")} hint={t("users.templateInboundsHint")}>
          {inbounds.loading ? <SkeletonRows rows={2} cols={2} /> : (
            <div className="sk-inbound-matrix">
              {xrayProtos.map(([proto, list]) => {
                const vis = PROTO_VISUAL[proto] || { icon: "•", hue: "var(--sk-accent)", label: proto.toUpperCase() };
                return (
                    <div key={proto} className="sk-inbound-matrix-cell" style={{ "--proto-hue": vis.hue } as CSSProperties}>
                    <div className="sk-inbound-matrix-head">
                      <span className="sk-inbound-matrix-icon" aria-hidden>{vis.icon}</span>
                      <span>{vis.label}</span>
                    </div>
                    <div className="sk-inbound-matrix-tags">
                      {list.map((i) => {
                        const active = (inbSel[proto] || []).includes(i.tag);
                        return (
                          <button
                            key={i.tag}
                            type="button"
                            className={`sk-inbound-tag ${active ? "active" : ""}`}
                            onClick={() => toggleTag(proto, i.tag)}
                          >
                            <span className="sk-inbound-tag-check" aria-hidden>{active ? "✓" : ""}</span>
                            {i.tag}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
              {nativeProtos.map((proto) => {
                const vis = PROTO_VISUAL[proto] || { icon: "•", hue: "var(--sk-accent)", label: proto.toUpperCase() };
                const active = !!nativeOn[proto];
                return (
                  <div key={proto} className="sk-inbound-matrix-cell" style={{ "--proto-hue": vis.hue } as CSSProperties}>
                    <div className="sk-inbound-matrix-head">
                      <span className="sk-inbound-matrix-icon" aria-hidden>{vis.icon}</span>
                      <span>{vis.label}</span>
                    </div>
                    <div className="sk-inbound-matrix-tags">
                      <button
                        type="button"
                        className={`sk-inbound-tag ${active ? "active" : ""}`}
                        onClick={() => toggleNative(proto)}
                      >
                        <span className="sk-inbound-tag-check" aria-hidden>{active ? "✓" : ""}</span>
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
