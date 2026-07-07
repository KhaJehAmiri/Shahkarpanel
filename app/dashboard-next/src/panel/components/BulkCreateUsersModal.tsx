import { FC, useEffect, useMemo, useState, type ChangeEvent } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { InboundsByProtocol, NodeItem } from "../api/types";
import { useFetch } from "../lib/useFetch";
import { dataLimitToBytes, type DataLimitUnit } from "../lib/data-limit";
import {
  NXPANEL_WG_KIND,
  defaultProtoInboundTags,
  deriveSsMethodFromInbounds,
  inboundMatchesSsMethod,
  protocolAssignable,
  ssMethodFromInbound,
  toggleSsInboundTag,
  wgKindForSubmit,
} from "../lib/userHelpers";
import { UserTemplateRow } from "./UserTemplates";
import { Button, Checkbox, Field, Input, Modal, Select, useToast } from "./ui";
import "./bulk-create-modal.css";

const NATIVE_PROTOCOLS = ["wireguard", "amneziawg", "hysteria2", "tuic", "anytls"] as const;
const PROTO_ORDER = ["vless", "vmess", "trojan", "shadowsocks", "wireguard", "amneziawg", "hysteria2", "tuic", "anytls"];
const PROTO_LABEL: Record<string, string> = {
  vless: "VLESS", vmess: "VMess", trojan: "Trojan", shadowsocks: "Shadowsocks",
  wireguard: "WireGuard", amneziawg: "AmneziaWG", hysteria2: "Hysteria2", tuic: "TUIC", anytls: "AnyTLS",
};
const PROTO_VISUAL: Record<string, { icon: string; hue: string }> = {
  vless: { icon: "⚡", hue: "#2ee0c4" },
  vmess: { icon: "◆", hue: "#6366f1" },
  trojan: { icon: "🔒", hue: "#f59e0b" },
  shadowsocks: { icon: "🛡", hue: "#38bdf8" },
  wireguard: { icon: "⬡", hue: "#a78bfa" },
  amneziawg: { icon: "🛡", hue: "#22d3ee" },
  hysteria2: { icon: "🚀", hue: "#f472b6" },
  tuic: { icon: "◉", hue: "#34d399" },
  anytls: { icon: "🛡", hue: "#a78bfa" },
};

type TabId = "basic" | "protocols" | "limits";
type ProtoState = { enabled: boolean; tags: string[]; flow: string; method: string };

interface Props {
  open: boolean;
  onClose: () => void;
  onDone: () => void;
  templates: UserTemplateRow[];
}

export const BulkCreateUsersModal: FC<Props> = ({ open, onClose, onDone, templates }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const inbounds = useFetch<InboundsByProtocol>(() => api.get("/inbounds"), []);
  const nodes = useFetch<NodeItem[]>(() => api.get("/nodes"), []);
  const routingPresets = useFetch<{ presets: Record<string, { label: string }> }>(
    () => api.get("/routing/presets"),
    [],
  );
  const dnsPresets = useFetch<{ presets: Record<string, { label: string }> }>(
    () => api.get("/routing/dns-presets"),
    [],
  );

  const [tab, setTab] = useState<TabId>("basic");
  const [useTemplate, setUseTemplate] = useState(false);
  const [templateId, setTemplateId] = useState<number | "">("");
  const [count, setCount] = useState(10);
  const [prefix, setPrefix] = useState("");
  const [suffix, setSuffix] = useState("");
  const [status, setStatus] = useState("active");
  const [note, setNote] = useState("");
  const [unlimited, setUnlimited] = useState(true);
  const [dataLimitUnit, setDataLimitUnit] = useState<DataLimitUnit>("GB");
  const [dataLimitValue, setDataLimitValue] = useState("");
  const [noExpire, setNoExpire] = useState(true);
  const [expireDate, setExpireDate] = useState("");
  const [reset, setReset] = useState("no_reset");
  const [speedUp, setSpeedUp] = useState("");
  const [speedDown, setSpeedDown] = useState("");
  const [deviceLimit, setDeviceLimit] = useState("");
  const [sessionLimit, setSessionLimit] = useState("");
  const [clientProfile, setClientProfile] = useState("normal");
  const [routingPreset, setRoutingPreset] = useState("");
  const [dnsPreset, setDnsPreset] = useState("");
  const [protos, setProtos] = useState<Record<string, ProtoState>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setTab("basic");
    inbounds.reload();
    nodes.reload();
    routingPresets.reload();
    dnsPresets.reload();
    if (templates.length) setTemplateId(templates[0].id);
  }, [open]);

  useEffect(() => {
    if (!open || !inbounds.data) return;
    const awgTags = (inbounds.data.amneziawg || []).map((i) => i.tag);
    const next: Record<string, ProtoState> = {};
    Object.keys(inbounds.data).forEach((proto) => {
      if (proto === "amneziawg") return;
      const tags = inbounds.data![proto].map((i) => i.tag);
      next[proto] = { enabled: false, tags, flow: "", method: "chacha20-ietf-poly1305" };
    });
    next.amneziawg = { enabled: false, tags: awgTags, flow: "", method: "" };
    next.wireguard = { enabled: false, tags: [], flow: "", method: "" };
    for (const p of ["hysteria2", "tuic", "anytls"]) {
      next[p] = { enabled: false, tags: [], flow: "", method: "" };
    }
    setProtos(next);
  }, [open, inbounds.data]);

  useEffect(() => {
    if (useTemplate && tab === "protocols") setTab("limits");
  }, [useTemplate, tab]);

  const availableProtos = PROTO_ORDER.filter((p) => {
    if (!protos[p]) return false;
    if (protos[p].enabled) return true;
    return protocolAssignable(p, inbounds.data ?? undefined, nodes.data ?? undefined);
  });

  const enabledProtoLabels = useMemo(() => {
    const names = Object.entries(protos)
      .filter(([, v]) => v.enabled)
      .map(([p]) => PROTO_LABEL[p] || p);
    return names.length ? names.join(", ") : "—";
  }, [protos]);

  const setProto = (p: string, patch: Partial<ProtoState>) => {
    setProtos((s) => ({ ...s, [p]: { ...s[p], ...patch } }));
  };

  const toggleTag = (p: string, tag: string) => {
    setProtos((s) => {
      const cur = s[p];
      const ibList = p === "amneziawg"
        ? (inbounds.data?.amneziawg || [])
        : (inbounds.data?.[p] || []);
      const tags = p === "shadowsocks"
        ? toggleSsInboundTag(cur.tags, tag, ibList)
        : (cur.tags.includes(tag) ? cur.tags.filter((x) => x !== tag) : [...cur.tags, tag]);
      return { ...s, [p]: { ...cur, tags } };
    });
  };

  const toggleProto = (p: string) => {
    const enabling = !protos[p]?.enabled;
    const isNative = NATIVE_PROTOCOLS.includes(p as typeof NATIVE_PROTOCOLS[number]);
    const tags = enabling && !isNative ? defaultProtoInboundTags(p, inbounds.data ?? undefined) : [];
    setProto(p, { enabled: enabling, ...(enabling && tags.length ? { tags } : {}) });
  };

  const buildPayload = () => {
    const enabled = Object.entries(protos).filter(([, v]) => v.enabled);
    const wgOn = !!(protos.wireguard?.enabled || protos.amneziawg?.enabled);
    let rows = enabled.filter(([p]) => p !== "amneziawg");
    if (wgOn && !rows.some(([p]) => p === "wireguard")) {
      rows.push(["wireguard", protos.wireguard || { enabled: true, tags: [], flow: "", method: "" }]);
    }

    const proxies: Record<string, Record<string, unknown>> = {};
    const inb: Record<string, string[]> = {};
    const awgTags = inbounds.data?.amneziawg?.map((i) => i.tag) || [];

    for (const [p, v] of rows) {
      const s: Record<string, unknown> = {};
      if (p === "vless" && v.flow) s.flow = v.flow;
      if (p === "shadowsocks") {
        const method = deriveSsMethodFromInbounds(v.tags, inbounds.data?.shadowsocks || []);
        if (method) s.method = method;
      }
      const wgKind = wgKindForSubmit(!!protos.wireguard?.enabled, !!protos.amneziawg?.enabled);
      if (p === "wireguard" && wgKind) s[NXPANEL_WG_KIND] = wgKind;
      if (NATIVE_PROTOCOLS.includes(p as typeof NATIVE_PROTOCOLS[number])) {
        proxies[p] = Object.keys(s).length ? s : (p === "wireguard" && wgKind ? { [NXPANEL_WG_KIND]: wgKind } : {});
        inb[p] = p === "wireguard" && protos.amneziawg?.enabled && awgTags.length
          ? protos.amneziawg.tags.filter((tag) => awgTags.includes(tag))
          : [];
      } else {
        proxies[p] = s;
        inb[p] = v.tags;
      }
    }
    return { proxies, inbounds: inb };
  };

  const validateBasic = () => {
    if (count < 1 || count > 500) {
      toast.push(t("bulkCreate.countRange"), "error");
      return false;
    }
    if (useTemplate && !templateId) {
      toast.push(t("bulkCreate.templateRequired"), "error");
      return false;
    }
    return true;
  };

  const validateProtocols = () => {
    if (useTemplate) return true;
    const enabled = Object.entries(protos).filter(([, v]) => v.enabled);
    if (!enabled.length) {
      toast.push(t("users.selectProtocol"), "error");
      return false;
    }
    const { inbounds: inb } = buildPayload();
    for (const [p] of enabled.filter(([x]) => x !== "amneziawg")) {
      if (!NATIVE_PROTOCOLS.includes(p as typeof NATIVE_PROTOCOLS[number]) && !(inb[p]?.length)) {
        toast.push(t("users.inboundRequired", { proto: PROTO_LABEL[p] || p }), "error");
        return false;
      }
    }
    return true;
  };

  const goNext = () => {
    if (tab === "basic" && !validateBasic()) return;
    if (tab === "protocols" && !validateProtocols()) return;
    if (tab === "basic") setTab(useTemplate ? "limits" : "protocols");
    else if (tab === "protocols") setTab("limits");
  };

  const goBack = () => {
    if (tab === "limits") setTab(useTemplate ? "basic" : "protocols");
    else if (tab === "protocols") setTab("basic");
  };

  const submit = async () => {
    if (!validateBasic() || !validateProtocols()) return;

    setBusy(true);
    try {
      const { proxies, inbounds: inb } = useTemplate ? { proxies: {}, inbounds: {} } : buildPayload();
      const body: Record<string, unknown> = {
        count,
        username_prefix: prefix || null,
        username_suffix: suffix || null,
        status,
        note: note || "",
        data_limit: unlimited || !dataLimitValue ? 0 : dataLimitToBytes(dataLimitValue, dataLimitUnit),
        expire: noExpire || !expireDate ? 0 : Math.floor(new Date(expireDate).getTime() / 1000),
        data_limit_reset_strategy: reset,
        client_profile: clientProfile,
        proxies,
        inbounds: inb,
      };
      if (useTemplate && templateId) body.template_id = templateId;
      if (speedUp.trim()) body.speed_limit_up = parseInt(speedUp, 10);
      if (speedDown.trim()) body.speed_limit_down = parseInt(speedDown, 10);
      if (deviceLimit.trim()) body.device_limit = parseInt(deviceLimit, 10);
      if (sessionLimit.trim()) body.session_limit_minutes = parseInt(sessionLimit, 10);
      if (routingPreset) body.routing_preset = routingPreset;
      if (dnsPreset) body.dns_policy = { preset: dnsPreset };
      if (status === "on_hold") {
        body.on_hold_expire_duration = !noExpire && expireDate
          ? Math.max(3600, Math.floor((new Date(expireDate).getTime() - Date.now()) / 1000))
          : 30 * 86400;
        body.expire = 0;
      }

      const r = await api.post<{ created: number; usernames: string[]; errors: string[]; duration_ms: number }>(
        "/users/bulk/create",
        body,
      );
      toast.push(t("bulkCreate.done", { n: r.created, ms: r.duration_ms }), r.errors?.length ? "error" : "success");
      if (r.errors?.length) toast.push(r.errors.slice(0, 3).join("\n"), "error");
      onDone();
      onClose();
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
    } finally {
      setBusy(false);
    }
  };

  const presetExpire = (days: number) => {
    setNoExpire(false);
    setExpireDate(new Date(Date.now() + days * 86400000).toISOString().slice(0, 10));
  };

  const tabs: { id: TabId; label: string; skip?: boolean }[] = [
    { id: "basic", label: t("bulkCreate.tabBasic") },
    { id: "protocols", label: t("bulkCreate.tabProtocols"), skip: useTemplate },
    { id: "limits", label: t("bulkCreate.tabLimits") },
  ];

  const enabledProtoRows = availableProtos.filter((p) => {
    if (!protos[p]?.enabled) return false;
    if (NATIVE_PROTOCOLS.includes(p as typeof NATIVE_PROTOCOLS[number])) return false;
    const ibList = p === "amneziawg"
      ? (inbounds.data?.amneziawg || [])
      : (inbounds.data?.[p] || []);
    return ibList.length > 0 || p === "vless";
  });

  if (!open) return null;

  return (
    <Modal
      open={open}
      formWide
      className="nx-bulk-create-shell"
      overlayClassName="nx-bulk-create-overlay"
      title={t("bulkCreate.title")}
      onClose={onClose}
      footer={
        <div className="nx-bulk-create-foot">
          <span className="nx-bulk-create-summary">
            {t("bulkCreate.summary", { count, protos: enabledProtoLabels })}
          </span>
          <div className="nx-bulk-create-foot-actions">
            <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
            {tab !== "basic" && (
              <Button variant="ghost" onClick={goBack}>{t("bulkCreate.back")}</Button>
            )}
            {tab !== "limits" ? (
              <Button variant="primary" onClick={goNext}>{t("bulkCreate.next")}</Button>
            ) : (
              <Button variant="primary" onClick={submit} disabled={busy}>
                {busy ? t("common.loading") : t("bulkCreate.submit")}
              </Button>
            )}
          </div>
        </div>
      }
    >
      <p className="nx-bulk-create-intro">{t("bulkCreate.descFull")}</p>

      <div className="nx-bulk-create-tabs" role="tablist">
        {tabs.map(({ id, label, skip }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            className={`nx-bulk-create-tab ${tab === id ? "active" : ""}`}
            disabled={skip}
            onClick={() => {
              if (id === "protocols" && useTemplate) return;
              if (id === "limits" && !validateBasic()) return;
              if (id === "limits" && !useTemplate && !validateProtocols()) return;
              setTab(id);
            }}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="nx-bulk-create-panel">
        {tab === "basic" && (
          <>
            <h4 className="nx-bulk-create-section-title">{t("bulkCreate.sectionIdentity")}</h4>
            <div className="nx-bulk-create-grid">
              <Field label={t("bulkCreate.count")}>
                <Input
                  type="number"
                  min={1}
                  max={500}
                  value={count}
                  onChange={(e: ChangeEvent<HTMLInputElement>) => setCount(Number(e.target.value) || 1)}
                />
              </Field>
              <Field label={t("common.status")}>
                <Select value={status} onChange={(e: ChangeEvent<HTMLSelectElement>) => setStatus(e.target.value)}>
                  <option value="active">{t("users.status.active")}</option>
                  <option value="on_hold">{t("users.status.on_hold")}</option>
                </Select>
              </Field>
              <Field label={t("bulkCreate.prefix")}>
                <Input value={prefix} onChange={(e: ChangeEvent<HTMLInputElement>) => setPrefix(e.target.value)} dir="ltr" />
              </Field>
              <Field label={t("bulkCreate.suffix")}>
                <Input value={suffix} onChange={(e: ChangeEvent<HTMLInputElement>) => setSuffix(e.target.value)} dir="ltr" />
              </Field>
              <div className="span-2">
                <Field label={`${t("users.noteLabel")} (${t("common.optional")})`}>
                  <Input value={note} onChange={(e: ChangeEvent<HTMLInputElement>) => setNote(e.target.value)} />
                </Field>
              </div>
            </div>

            {templates.length > 0 && (
              <div className="nx-bulk-create-template">
                <label className="nx-bulk-create-template-label">
                  <Checkbox checked={useTemplate} onChange={() => setUseTemplate((v) => !v)} />
                  <span>{t("bulkCreate.useTemplate")}</span>
                </label>
                {useTemplate && (
                  <div className="nx-bulk-create-template-body">
                    <Field label={t("users.template")}>
                      <Select
                        value={String(templateId)}
                        onChange={(e: ChangeEvent<HTMLSelectElement>) => setTemplateId(Number(e.target.value))}
                      >
                        {templates.map((tpl) => (
                          <option key={tpl.id} value={tpl.id}>{tpl.name || `#${tpl.id}`}</option>
                        ))}
                      </Select>
                    </Field>
                  </div>
                )}
              </div>
            )}
          </>
        )}

        {tab === "protocols" && (
          <>
            {useTemplate ? (
              <div className="nx-bulk-create-template-notice">{t("bulkCreate.templateSkipProtocols")}</div>
            ) : !inbounds.data ? (
              <span className="nx-faint">{t("common.loading")}</span>
            ) : (
              <>
                <h4 className="nx-bulk-create-section-title">{t("bulkCreate.sectionProtocols")}</h4>
                <div className="nx-proto-pick">
                  {availableProtos.map((p) => {
                    const vis = PROTO_VISUAL[p] || { icon: "🔗", hue: "var(--nx-accent)" };
                    const selected = !!protos[p]?.enabled;
                    return (
                      <button
                        key={p}
                        type="button"
                        className={`nx-proto-pick-card ${selected ? "selected" : ""}`}
                        style={{ "--proto-hue": vis.hue } as React.CSSProperties}
                        onClick={() => toggleProto(p)}
                      >
                        <span className="nx-proto-pick-check">✓</span>
                        <span className="nx-proto-icon">{vis.icon}</span>
                        <b>{PROTO_LABEL[p] || p}</b>
                        <small>
                          {NATIVE_PROTOCOLS.includes(p as typeof NATIVE_PROTOCOLS[number])
                            ? t("users.wgNativePeer")
                            : t("users.inboundCount", { n: inbounds.data?.[p]?.length || 0 })}
                        </small>
                      </button>
                    );
                  })}
                </div>

                {enabledProtoRows.length > 0 && (
                  <div className="nx-bulk-create-proto-config">
                    {enabledProtoRows.map((p) => {
                      const v = protos[p];
                      const ibList = p === "amneziawg"
                        ? (inbounds.data?.amneziawg || [])
                        : (inbounds.data?.[p] || []);
                      const ssRef = p === "shadowsocks"
                        ? (deriveSsMethodFromInbounds(v.tags, ibList) || ssMethodFromInbound(ibList[0] || {}))
                        : "";
                      return (
                        <div key={p} className="nx-bulk-create-proto-row">
                          <div className="nx-bulk-create-proto-row-head">
                            <b>{PROTO_LABEL[p] || p}</b>
                            {p === "shadowsocks" && (
                              <span className="nx-faint" style={{ fontSize: 11 }}>
                                {v.tags.length
                                  ? t("users.ssMethodValue", { method: ssRef })
                                  : t("users.ssMethodFromInbound")}
                              </span>
                            )}
                          </div>
                          {p === "vless" && (
                            <Field label="flow">
                              <Select
                                value={v.flow}
                                onChange={(e: ChangeEvent<HTMLSelectElement>) => setProto(p, { flow: e.target.value })}
                              >
                                <option value="">{t("users.flowNone")}</option>
                                <option value="xtls-rprx-vision">xtls-rprx-vision</option>
                              </Select>
                            </Field>
                          )}
                          {ibList.length > 0 && (
                            <div className="nx-bulk-create-inbound-chips">
                              {ibList.map((ib) => {
                                const ref = p === "shadowsocks" ? ssRef : "";
                                const ok = p !== "shadowsocks" || inboundMatchesSsMethod(ib.ss_method, ref || ssMethodFromInbound(ib));
                                const on = v.tags.includes(ib.tag);
                                return (
                                  <button
                                    key={ib.tag}
                                    type="button"
                                    className={`nx-bulk-create-inbound-chip ${on ? "on" : ""} ${ok ? "" : "disabled"}`}
                                    onClick={() => ok && toggleTag(p, ib.tag)}
                                    title={p === "shadowsocks" && ib.ss_method ? ib.ss_method : undefined}
                                  >
                                    {ib.tag}
                                    {p === "shadowsocks" && ib.ss_method && (
                                      <span style={{ opacity: 0.65 }}>· {ib.ss_method}</span>
                                    )}
                                  </button>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </>
            )}
          </>
        )}

        {tab === "limits" && (
          <>
            <h4 className="nx-bulk-create-section-title">{t("bulkCreate.sectionLimits")}</h4>
            <div className="nx-bulk-create-limits-row">
              <label className="nx-bulk-create-check">
                <Checkbox checked={unlimited} onChange={() => setUnlimited((x) => !x)} />
                <span>{t("users.unlimited")}</span>
              </label>
              {!unlimited && (
                <>
                  <Input
                    type="number"
                    min={0}
                    value={dataLimitValue}
                    onChange={(e: ChangeEvent<HTMLInputElement>) => setDataLimitValue(e.target.value)}
                    style={{ maxWidth: 100 }}
                  />
                  <Select
                    value={dataLimitUnit}
                    onChange={(e: ChangeEvent<HTMLSelectElement>) => setDataLimitUnit(e.target.value as DataLimitUnit)}
                  >
                    <option value="MB">MB</option>
                    <option value="GB">GB</option>
                  </Select>
                </>
              )}
            </div>

            <div className="nx-bulk-create-grid">
              <Field label={t("users.resetStrategy")}>
                <Select value={reset} onChange={(e: ChangeEvent<HTMLSelectElement>) => setReset(e.target.value)}>
                  {["no_reset", "day", "week", "month", "year"].map((r) => (
                    <option key={r} value={r}>{t(`users.resetStrategies.${r}`, r)}</option>
                  ))}
                </Select>
              </Field>
              <Field label={t("users.clientProfile")}>
                <Select value={clientProfile} onChange={(e: ChangeEvent<HTMLSelectElement>) => setClientProfile(e.target.value)}>
                  <option value="normal">{t("users.profile.normal")}</option>
                  <option value="gamer">{t("users.profile.gamer")}</option>
                  <option value="trader">{t("users.profile.trader")}</option>
                </Select>
              </Field>
              <Field label={t("bulkCreate.speedUp")}>
                <Input
                  type="number"
                  min={0}
                  placeholder="Mbps"
                  value={speedUp}
                  onChange={(e: ChangeEvent<HTMLInputElement>) => setSpeedUp(e.target.value)}
                  dir="ltr"
                />
              </Field>
              <Field label={t("bulkCreate.speedDown")}>
                <Input
                  type="number"
                  min={0}
                  placeholder="Mbps"
                  value={speedDown}
                  onChange={(e: ChangeEvent<HTMLInputElement>) => setSpeedDown(e.target.value)}
                  dir="ltr"
                />
              </Field>
              <Field label={t("bulkCreate.deviceLimit")}>
                <Input
                  type="number"
                  min={0}
                  value={deviceLimit}
                  onChange={(e: ChangeEvent<HTMLInputElement>) => setDeviceLimit(e.target.value)}
                />
              </Field>
              <Field label={t("bulkCreate.sessionLimit")}>
                <Input
                  type="number"
                  min={0}
                  value={sessionLimit}
                  onChange={(e: ChangeEvent<HTMLInputElement>) => setSessionLimit(e.target.value)}
                />
              </Field>
            </div>

            <h4 className="nx-bulk-create-section-title">{t("users.expire")}</h4>
            <label className="nx-bulk-create-check">
              <Checkbox checked={noExpire} onChange={() => setNoExpire((x) => !x)} />
              <span>{t("users.never")}</span>
            </label>
            {!noExpire && (
              <>
                <Input
                  type="date"
                  value={expireDate}
                  onChange={(e: ChangeEvent<HTMLInputElement>) => setExpireDate(e.target.value)}
                  style={{ marginTop: 10, maxWidth: 220 }}
                />
                <div className="nx-bulk-create-expire-presets">
                  {[7, 30, 90, 365].map((d) => (
                    <Button key={d} size="sm" variant="ghost" onClick={() => presetExpire(d)}>{d}d</Button>
                  ))}
                </div>
              </>
            )}

            {(routingPresets.data || dnsPresets.data) && (
              <div className="nx-bulk-create-grid" style={{ marginTop: 16 }}>
                  {routingPresets.data && (
                    <Field label={t("users.routingPreset", { defaultValue: "Routing preset" })}>
                      <Select value={routingPreset} onChange={(e: ChangeEvent<HTMLSelectElement>) => setRoutingPreset(e.target.value)}>
                        <option value="">{t("common.none", { defaultValue: "None" })}</option>
                        {Object.entries(routingPresets.data.presets || {}).map(([id, meta]) => (
                          <option key={id} value={id}>{meta.label || id}</option>
                        ))}
                      </Select>
                    </Field>
                  )}
                  {dnsPresets.data && (
                    <Field label={t("users.dnsPreset", { defaultValue: "DNS policy" })}>
                      <Select value={dnsPreset} onChange={(e: ChangeEvent<HTMLSelectElement>) => setDnsPreset(e.target.value)}>
                        <option value="">{t("common.none", { defaultValue: "None" })}</option>
                        {Object.entries(dnsPresets.data.presets || {}).map(([id, meta]) => (
                          <option key={id} value={id}>{meta.label || id}</option>
                        ))}
                      </Select>
                    </Field>
                  )}
                </div>
            )}
          </>
        )}
      </div>
    </Modal>
  );
};
