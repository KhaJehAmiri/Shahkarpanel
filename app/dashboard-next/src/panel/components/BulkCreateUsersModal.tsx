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
  type AssignableNativeProtocols,
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

interface SubEndpointRow {
  id: number;
  slug: string;
  host: string | null;
  path_prefix: string;
  listen_port: number | null;
  inbound_tag: string | null;
  enabled: boolean;
}

interface CreatedUserLink {
  username: string;
  subscription_url: string;
  public_subscription_url: string;
  sub_token?: string | null;
}

interface BulkCreateResult {
  created: number;
  usernames: string[];
  users: CreatedUserLink[];
  errors: string[];
  duration_ms: number;
}

interface Props {
  open: boolean;
  onClose: () => void;
  onDone: () => void;
  templates: UserTemplateRow[];
}

function isPanelEndpoint(ep: SubEndpointRow): boolean {
  if (!ep.enabled) return false;
  if (ep.inbound_tag) return false;
  if (ep.slug === "default") return false;
  if (ep.slug.endsWith("-json") || ep.slug.endsWith("-clash")) return false;
  return true;
}

function tagMatchesPanel(tag: string, slug: string): boolean {
  return tag === slug || tag.startsWith(`${slug}-`);
}

async function copyText(text: string): Promise<boolean> {
  if (!text) return false;
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch { /* fall through */ }
  try {
    const a = document.createElement("textarea");
    a.value = text;
    a.setAttribute("readonly", "");
    a.style.position = "fixed";
    a.style.top = "-9999px";
    document.body.appendChild(a);
    a.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(a);
    return ok;
  } catch {
    return false;
  }
}

export const BulkCreateUsersModal: FC<Props> = ({ open, onClose, onDone, templates }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const inbounds = useFetch<InboundsByProtocol>(() => api.get("/inbounds"), []);
  const nodes = useFetch<NodeItem[]>(() => api.get("/nodes"), []);
  const nativeCaps = useFetch<AssignableNativeProtocols>(
    () => api.get("/assignable-native-protocols"),
    [],
  );
  const endpoints = useFetch<SubEndpointRow[]>(() => api.get("/subscription-endpoints"), []);
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
  /** null = auto-balance to least-loaded p panel; number = pinned panel id */
  const [panelId, setPanelId] = useState<number | null>(null);
  const balance = useFetch<{
    panels: Array<{ id: number; slug: string; host: string | null; user_count: number }>;
    next: { id: number; slug: string; host: string | null; user_count: number } | null;
  }>(() => api.get("/subscription-endpoints/balance"), []);
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
  const [result, setResult] = useState<BulkCreateResult | null>(null);

  const panels = useMemo(() => {
    const fromApi = (endpoints.data || [])
      .filter(isPanelEndpoint)
      .sort((a, b) => a.slug.localeCompare(b.slug));
    if (fromApi.length) return fromApi;
    // Resellers cannot list full endpoints — use balance rows for pin cards.
    return (balance.data?.panels || [])
      .slice()
      .sort((a, b) => a.slug.localeCompare(b.slug))
      .map((p) => ({
        id: p.id,
        slug: p.slug,
        host: p.host,
        path_prefix: "sub",
        listen_port: 2096,
        enabled: true,
        inbound_tag: null,
      })) as SubEndpointRow[];
  }, [endpoints.data, balance.data]);
  const selectedPanel = panels.find((p) => p.id === panelId) || null;

  useEffect(() => {
    if (!open) return;
    setTab("basic");
    setResult(null);
    setPanelId(null); // default: auto-balance
    inbounds.reload();
    nodes.reload();
    nativeCaps.reload();
    endpoints.reload();
    balance.reload();
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
    return protocolAssignable(
      p,
      inbounds.data ?? undefined,
      nodes.data ?? undefined,
      nativeCaps.data,
    );
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

  const filterTagsForPanel = (tags: string[]): string[] => {
    if (!selectedPanel) return tags;
    const matched = tags.filter((tag) => tagMatchesPanel(tag, selectedPanel.slug));
    // Shared tags (e.g. in1) when the panel has no dedicated inbound rows.
    return matched.length ? matched : tags;
  };

  const toggleProto = (p: string) => {
    const enabling = !protos[p]?.enabled;
    const isNative = NATIVE_PROTOCOLS.includes(p as typeof NATIVE_PROTOCOLS[number]);
    const all = enabling && !isNative ? defaultProtoInboundTags(p, inbounds.data ?? undefined) : [];
    const tags = filterTagsForPanel(all);
    setProto(p, { enabled: enabling, ...(enabling && tags.length ? { tags } : {}) });
  };

  const selectPanel = (id: number | null) => {
    setPanelId(id);
    const panel = panels.find((p) => p.id === id) || null;
    if (panel) {
      const want = `${panel.slug}_`;
      setPrefix((prev) => (!prev || /^[a-z0-9]+_$/i.test(prev) ? want : prev));
      // Re-filter already-enabled protocol tags to the chosen panel.
      setProtos((s) => {
        const next = { ...s };
        for (const [p, v] of Object.entries(next)) {
          if (!v.enabled || NATIVE_PROTOCOLS.includes(p as typeof NATIVE_PROTOCOLS[number])) continue;
          const ibList = (inbounds.data?.[p] || []).map((i) => i.tag);
          const matched = ibList.filter((tag) => tagMatchesPanel(tag, panel.slug));
          next[p] = { ...v, tags: matched.length ? matched : v.tags.length ? v.tags : ibList };
        }
        return next;
      });
    }
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
      if (panelId != null) body.subscription_endpoint_id = panelId;
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

      const r = await api.post<BulkCreateResult>("/users/bulk/create", body);
      toast.push(t("bulkCreate.done", { n: r.created, ms: r.duration_ms }), r.errors?.length ? "error" : "success");
      if (r.errors?.length) toast.push(r.errors.slice(0, 3).join("\n"), "error");
      onDone();
      setResult({
        ...r,
        users: (r.users || []).map((u) => ({
          ...u,
          public_subscription_url: u.public_subscription_url || u.subscription_url || "",
        })),
      });
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
    } finally {
      setBusy(false);
    }
  };

  const resultLinks = useMemo(() => {
    if (!result) return [] as { username: string; url: string }[];
    return (result.users || []).map((u) => ({
      username: u.username,
      url: (u.public_subscription_url || u.subscription_url || "").trim(),
    })).filter((x) => x.url);
  }, [result]);

  const copyAllLinks = async () => {
    const text = resultLinks.map((x) => x.url).join("\n");
    const ok = await copyText(text);
    toast.push(ok ? t("bulkCreate.copiedAll", { n: resultLinks.length }) : t("common.error"), ok ? "success" : "error");
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

  if (result) {
    return (
      <Modal
        open
        formWide
        className="nx-bulk-create-shell nx-bulk-create-results"
        overlayClassName="nx-bulk-create-overlay"
        title={t("bulkCreate.resultsTitle", { n: result.created })}
        onClose={onClose}
        footer={
          <div className="nx-bulk-create-foot">
            <span className="nx-bulk-create-summary">
              {t("bulkCreate.resultsSummary", { n: resultLinks.length, panel: selectedPanel?.slug || "—" })}
            </span>
            <div className="nx-bulk-create-foot-actions">
              <Button variant="ghost" onClick={onClose}>{t("common.close")}</Button>
              <Button variant="primary" onClick={copyAllLinks} disabled={!resultLinks.length}>
                {t("bulkCreate.copyAll")}
              </Button>
            </div>
          </div>
        }
      >
        <div className="nx-bulk-create-results-body">
          <p className="nx-bulk-create-intro">{t("bulkCreate.resultsDesc")}</p>
          <div className="nx-bulk-create-results-toolbar">
            <Button size="sm" variant="primary" onClick={copyAllLinks} disabled={!resultLinks.length}>
              {t("bulkCreate.copyAll")}
            </Button>
            <span className="nx-faint">{t("bulkCreate.resultsCount", { n: resultLinks.length })}</span>
          </div>
          <div className="nx-bulk-create-results-list">
            {resultLinks.map((row) => (
              <div key={row.username} className="nx-bulk-create-result-row">
                <div className="nx-bulk-create-result-meta">
                  <strong dir="ltr">{row.username}</strong>
                  <code dir="ltr">{row.url}</code>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={async () => {
                    const ok = await copyText(row.url);
                    toast.push(ok ? t("common.copied") : t("common.error"), ok ? "success" : "error");
                  }}
                >
                  {t("common.copy")}
                </Button>
              </div>
            ))}
            {!resultLinks.length && (
              <div className="nx-faint">{t("bulkCreate.noLinks")}</div>
            )}
          </div>
          {!!result.errors?.length && (
            <div className="nx-bulk-create-results-errors">
              {result.errors.slice(0, 8).map((err) => (
                <div key={err}>{err}</div>
              ))}
            </div>
          )}
        </div>
      </Modal>
    );
  }

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
            {t("bulkCreate.summary", {
              count,
              protos: enabledProtoLabels,
              panel: selectedPanel?.slug || t("bulkCreate.panelNone"),
            })}
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
            <h4 className="nx-bulk-create-section-title">{t("bulkCreate.sectionPanel")}</h4>
            <p className="nx-faint" style={{ fontSize: 12.5, margin: "0 0 12px" }}>
              {t("bulkCreate.panelBalanceHint", "Auto picks the p-panel with the fewest users (srw1…srw9). Pin one only if you need a fixed host.")}
            </p>
            {!endpoints.data && !balance.data ? (
              <span className="nx-faint">{t("common.loading")}</span>
            ) : panels.length === 0 && !balance.data?.panels?.length ? (
              <div className="nx-faint">{t("bulkCreate.noPanels")}</div>
            ) : (
              <div className="nx-bulk-create-panels">
                <button
                  type="button"
                  className={`nx-bulk-create-panel-card ${panelId == null ? "selected" : ""}`}
                  onClick={() => setPanelId(null)}
                >
                  <span className="nx-bulk-create-panel-check">✓</span>
                  <b dir="ltr">{t("bulkCreate.autoBalance", "Auto balance")}</b>
                  <small dir="ltr">
                    {balance.data?.next
                      ? t("bulkCreate.nextPanel", "Next → {{slug}} ({{n}} users)", {
                        slug: balance.data.next.slug,
                        n: balance.data.next.user_count,
                      })
                      : t("bulkCreate.autoBalanceHint", "Least-loaded panel")}
                  </small>
                </button>
                {panels.map((p) => {
                  const on = panelId === p.id;
                  const count = balance.data?.panels?.find((b) => b.id === p.id)?.user_count;
                  return (
                    <button
                      key={p.id}
                      type="button"
                      className={`nx-bulk-create-panel-card ${on ? "selected" : ""}`}
                      onClick={() => selectPanel(p.id)}
                    >
                      <span className="nx-bulk-create-panel-check">✓</span>
                      <b dir="ltr">{p.slug}</b>
                      <small dir="ltr">
                        {p.host || "—"}
                        {p.listen_port ? `:${p.listen_port}` : ""}
                        {" · /"}{p.path_prefix}/
                        {count != null ? ` · ${count}` : ""}
                      </small>
                    </button>
                  );
                })}
              </div>
            )}

            <h4 className="nx-bulk-create-section-title" style={{ marginTop: 18 }}>{t("bulkCreate.sectionIdentity")}</h4>
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
                              {(selectedPanel
                                ? (() => {
                                    const matched = ibList.filter((ib) => tagMatchesPanel(ib.tag, selectedPanel.slug));
                                    return matched.length ? matched : ibList;
                                  })()
                                : ibList
                              ).map((ib) => {
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
