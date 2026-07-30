"use client";

import { FC, useEffect, useMemo, useState, type ChangeEvent } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../api/client";
import { useFetch } from "../../lib/useFetch";
import { Button, Field, Input, Modal, Select, Toggle } from "../ui";
import { ExternalProxyEditor } from "./ExternalProxyEditor";
import { StructuredHostJsonFields } from "./StructuredHostJsonFields";
import { HOST_ALPN_PRESETS, HOST_FINGERPRINT_PRESETS } from "../../lib/xrayHelpers";
import type { NodeItem } from "../../api/types";
import { hostTagLabel, isNativeHostTag, type HostRecord } from "./types";
import "./host-editor-modal.css";

type TabId = "basic" | "security" | "advanced";

interface Props {
  open: boolean;
  mode: "add" | "edit";
  inboundTag: string;
  inboundTags: string[];
  initial: HostRecord;
  busy?: boolean;
  onClose: () => void;
  onSave: (tag: string, host: HostRecord) => void;
}

const REMARK_TOKENS = [
  "{REGION_FLAG}",
  "{REGION_NAME}",
  "{USERNAME}",
  "{PROTOCOL}",
  "{PORT}",
  "{DATA_LEFT}",
  "{DATA_LIMIT}",
  "{DATA_USAGE}",
  "{EXPIRE_DATE}",
  "{JALALI_EXPIRE_DATE}",
  "{DAYS_LEFT}",
] as const;

const ADDRESS_TOKENS = ["{SERVER_IP}", "{NODE_IP}", "{PORT}"] as const;

function TokenPanel({
  label,
  tokens,
  onPick,
}: {
  label: string;
  tokens: readonly string[];
  onPick: (token: string) => void;
}) {
  return (
    <div className="sk-host-token-panel">
      <div className="sk-host-token-panel-head">
        <span className="sk-host-placeholder-label">{label}</span>
      </div>
      <div className="sk-host-placeholders">
        {tokens.map((token) => (
          <button key={token} type="button" className="sk-host-chip" onClick={() => onPick(token)}>
            {token}
          </button>
        ))}
      </div>
    </div>
  );
}

export const HostEditorModal: FC<Props> = ({
  open,
  mode,
  inboundTag,
  inboundTags,
  initial,
  busy,
  onClose,
  onSave,
}) => {
  const { t } = useTranslation();
  const [tab, setTab] = useState<TabId>("basic");
  const [tag, setTag] = useState(inboundTag);
  const [form, setForm] = useState<HostRecord>(initial);
  const regions = useFetch<{ regions: { code: string; flag: string; name: string }[] }>(
    () => api.get("/hosts/region-presets"),
    [],
  );
  const nodes = useFetch<NodeItem[]>(() => (open ? api.get("/nodes") : Promise.resolve([])), [open]);
  const isNative = isNativeHostTag(tag);

  useEffect(() => {
    if (!open) return;
    setTab("basic");
    setTag(inboundTag);
    setForm({ ...initial, region: initial.region || "" });
  }, [open, inboundTag, initial]);

  const selectedNodeIds = useMemo(() => {
    const raw = (form.node_ids || "").trim();
    if (!raw) return new Set<number>();
    return new Set(
      raw
        .split(",")
        .map((p) => parseInt(p.trim(), 10))
        .filter((n) => Number.isFinite(n)),
    );
  }, [form.node_ids]);

  const toggleNodeId = (id: number) => {
    const next = new Set(selectedNodeIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    set("node_ids", [...next].sort((a, b) => a - b).join(","));
  };

  const set = <K extends keyof HostRecord>(key: K, value: HostRecord[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const insertToken = (field: "address" | "remark", token: string) => {
    const current = String(form[field] || "").trim();
    set(field, (current ? `${current} ${token}` : token) as HostRecord[typeof field]);
  };

  const addressHasRegionFlag = useMemo(
    () => /\{REGION_FLAG\}|\{REGION_NAME\}/.test(form.address || ""),
    [form.address],
  );

  const tabs: { id: TabId; label: string }[] = [
    { id: "basic", label: t("infra.hostTabBasic") },
    ...(!isNative ? [{ id: "security" as const, label: t("infra.hostTabSecurity") }] : []),
    { id: "advanced", label: t("infra.hostTabAdvanced") },
  ];

  return (
    <Modal
      open={open}
      title={mode === "add" ? t("infra.hostAddTitle") : t("infra.hostEditTitle")}
      onClose={onClose}
      formWide
      className="sk-host-editor-shell"
      overlayClassName="sk-host-editor-overlay"
      footer={
        <>
          <Button variant="ghost" disabled={busy} onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="primary"
            disabled={busy || !form.remark.trim() || !tag}
            onClick={() => onSave(tag, form)}
          >
            {t("common.save")}
          </Button>
        </>
      }
    >
      <div className="sk-host-editor-body">
        <div className="sk-host-modal-tabs">
          {tabs.map((tb) => (
            <button
              key={tb.id}
              type="button"
              className={`sk-host-modal-tab ${tab === tb.id ? "active" : ""}`}
              onClick={() => setTab(tb.id)}
            >
              {tb.label}
            </button>
          ))}
        </div>

        <div className="sk-host-editor-scroll">
          {tab === "basic" && (
            <>
              <section className="sk-host-section">
                <h3 className="sk-host-section-title">{t("infra.hostSectionDisplay")}</h3>
                <div className="sk-host-modal-grid">
                  <Field label={t("infra.hostRegion")} hint={t("infra.hostRegionHint")}>
                    <Select
                      value={form.region || ""}
                      onChange={(e: ChangeEvent<HTMLSelectElement>) => set("region", e.target.value)}
                    >
                      <option value="">{t("infra.hostRegionAuto")}</option>
                      {(regions.data?.regions || []).map((r) => (
                        <option key={r.code} value={r.code}>
                          {r.flag} {r.name} ({r.code})
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label={t("infra.hostInbound")}>
                    <Select
                      value={tag}
                      onChange={(e: ChangeEvent<HTMLSelectElement>) => setTag(e.target.value)}
                      disabled={mode === "edit"}
                    >
                      {inboundTags.map((tg) => (
                        <option key={tg} value={tg}>
                          {hostTagLabel(tg)}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  {isNative && (
                    <p className="sk-host-callout">{t("infra.hostNativeHint")}</p>
                  )}
                  <div className="sk-host-span-2">
                    <Field label={t("infra.remark")} hint={t("infra.hostRemarkHintShort")}>
                      <Input value={form.remark} onChange={(e) => set("remark", e.target.value)} dir="ltr" />
                    </Field>
                  </div>
                  <TokenPanel
                    label={t("infra.hostRemarkTokens")}
                    tokens={REMARK_TOKENS}
                    onPick={(token) => insertToken("remark", token)}
                  />
                  <p className="sk-host-callout">{t("infra.hostRemarkHintDetail")}</p>
                </div>
              </section>

              <section className="sk-host-section">
                <h3 className="sk-host-section-title">{t("infra.hostSectionConnection")}</h3>
                <div className="sk-host-modal-grid">
                  <Field label={t("infra.address")} hint={t("infra.hostAddressHint")}>
                    <Input
                      value={form.address}
                      onChange={(e) => set("address", e.target.value)}
                      placeholder={t("infra.hostAddressPlaceholder")}
                      dir="ltr"
                    />
                  </Field>
                  <Field label={t("infra.port")} hint={t("infra.hostPortCdnHint")}>
                    <Input
                      type="number"
                      value={form.port ?? ""}
                      onChange={(e) => set("port", e.target.value ? parseInt(e.target.value, 10) : null)}
                      placeholder={t("infra.hostPortPlaceholder")}
                      dir="ltr"
                    />
                  </Field>
                  {addressHasRegionFlag && (
                    <p className="sk-host-callout warn">{t("infra.hostAddressRegionWarning")}</p>
                  )}
                  <TokenPanel
                    label={t("infra.hostAddressTokens")}
                    tokens={ADDRESS_TOKENS}
                    onPick={(token) => insertToken("address", token)}
                  />
                  <p className="sk-host-callout">{t("infra.hostEchCdnWarning")}</p>
                </div>
              </section>

              <section className="sk-host-section">
                <h3 className="sk-host-section-title">{t("infra.hostSectionTls")}</h3>
                <div className="sk-host-modal-grid">
                  <Field label={t("infra.hostSni")}>
                    <Input value={form.sni} onChange={(e) => set("sni", e.target.value)} dir="ltr" />
                  </Field>
                  <Field label={t("infra.hostHost")}>
                    <Input value={form.host} onChange={(e) => set("host", e.target.value)} dir="ltr" />
                  </Field>
                  <Field label={t("infra.hostPath")}>
                    <Input value={form.path} onChange={(e) => set("path", e.target.value)} dir="ltr" />
                  </Field>
                  <div className="sk-host-toggle-row">
                    <Toggle on={!form.is_disabled} onChange={(v) => set("is_disabled", !v)} label={t("common.enable")} />
                    <span className="sk-host-toggle-label">{t("common.enable")}</span>
                  </div>
                </div>
              </section>
            </>
          )}

          {tab === "security" && (
            <div className="sk-host-modal-grid">
              <Field label={t("infra.hostTls")}>
                <Select
                  value={form.security || "inbound_default"}
                  onChange={(e: ChangeEvent<HTMLSelectElement>) => set("security", e.target.value)}
                >
                  {["inbound_default", "same", "none", "tls", "reality"].map((s) => (
                    <option key={s} value={s}>
                      {s === "inbound_default" || s === "same" ? t("infra.hostSecuritySame") : s}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t("infra.hostAlpn")}>
                <Select
                  value={form.alpn || ""}
                  onChange={(e: ChangeEvent<HTMLSelectElement>) => set("alpn", e.target.value)}
                >
                  {HOST_ALPN_PRESETS.map((v) => (
                    <option key={v || "none"} value={v}>{v || t("common.none")}</option>
                  ))}
                </Select>
              </Field>
              <Field label={t("infra.hostFp")}>
                <Select
                  value={form.fingerprint || ""}
                  onChange={(e: ChangeEvent<HTMLSelectElement>) => set("fingerprint", e.target.value)}
                >
                  {HOST_FINGERPRINT_PRESETS.map((v) => (
                    <option key={v || "none"} value={v}>{v || t("common.none")}</option>
                  ))}
                </Select>
              </Field>
              <div className="sk-host-toggles">
                <div className="sk-host-toggle-row">
                  <Toggle on={!!form.allowinsecure} onChange={(v) => set("allowinsecure", v)} label={t("infra.hostInsecure")} />
                  <span className="sk-host-toggle-label">{t("infra.hostInsecure")}</span>
                </div>
                <div className="sk-host-toggle-row">
                  <Toggle on={!!form.mux_enable} onChange={(v) => set("mux_enable", v)} label={t("infra.hostMux")} />
                  <span className="sk-host-toggle-label">{t("infra.hostMux")}</span>
                </div>
                <div className="sk-host-toggle-row">
                  <Toggle on={!!form.use_sni_as_host} onChange={(v) => set("use_sni_as_host", v)} label={t("infra.hostSniAsHost")} />
                  <span className="sk-host-toggle-label">{t("infra.hostSniAsHost")}</span>
                </div>
                <div className="sk-host-toggle-row">
                  <Toggle on={!!form.override_sni_from_address} onChange={(v) => set("override_sni_from_address", v)} label={t("infra.hostSniFromAddress")} />
                  <span className="sk-host-toggle-label">{t("infra.hostSniFromAddress")}</span>
                </div>
                <div className="sk-host-toggle-row">
                  <Toggle on={!!form.keep_sni_blank} onChange={(v) => set("keep_sni_blank", v)} label={t("infra.hostKeepSniBlank")} />
                  <span className="sk-host-toggle-label">{t("infra.hostKeepSniBlank")}</span>
                </div>
              </div>
            </div>
          )}

          {tab === "advanced" && (
            <div className="sk-host-modal-grid">
              <div className="sk-host-span-2">
                <Field
                  label={t("infra.hostNodeIds", "Nodes")}
                  hint={t(
                    "infra.hostNodeIdsHint",
                    "Empty = all nodes. Select specific servers so this host only appears for them in the subscription.",
                  )}
                >
                  <div className="sk-stack" style={{ gap: 6, maxHeight: 180, overflow: "auto" }}>
                    {(nodes.data || []).map((n) => (
                      <label key={n.id} className="sk-row" style={{ gap: 8, fontSize: 13 }}>
                        <input
                          type="checkbox"
                          checked={selectedNodeIds.has(n.id)}
                          onChange={() => toggleNodeId(n.id)}
                        />
                        <span>
                          #{n.id} {n.name}
                          <span className="sk-faint"> · {n.address}</span>
                          {n.core_kind ? (
                            <span className="sk-faint"> · {n.core_kind}</span>
                          ) : null}
                        </span>
                      </label>
                    ))}
                    {!nodes.data?.length && (
                      <span className="sk-faint">{t("common.noData")}</span>
                    )}
                  </div>
                  <Input
                    value={form.node_ids || ""}
                    onChange={(e) => set("node_ids", e.target.value)}
                    dir="ltr"
                    placeholder="1,2,3"
                    style={{ marginTop: 8 }}
                  />
                </Field>
              </div>
              <Field label={t("infra.hostVlessRoute")} hint={t("infra.hostVlessRouteHint")}>
                <Input value={form.vless_route || ""} onChange={(e) => set("vless_route", e.target.value)} dir="ltr" placeholder="443" />
              </Field>
              <Field label={t("infra.hostEch")}>
                <Input value={form.ech_config_list || ""} onChange={(e) => set("ech_config_list", e.target.value)} dir="ltr" />
              </Field>
              <Field label={t("infra.hostCertPin")}>
                <Input value={form.pinned_peer_cert_sha256 || ""} onChange={(e) => set("pinned_peer_cert_sha256", e.target.value)} dir="ltr" />
              </Field>
              <Field label={t("infra.hostVerifyCertByName")}>
                <Input value={form.verify_peer_cert_by_name || ""} onChange={(e) => set("verify_peer_cert_by_name", e.target.value)} dir="ltr" />
              </Field>
              <Field label={t("infra.hostExcludeFormats")} hint={t("infra.hostExcludeFormatsHint")}>
                <Input value={form.exclude_from_sub_types || ""} onChange={(e) => set("exclude_from_sub_types", e.target.value)} dir="ltr" placeholder="clash,json" />
              </Field>
              <Field label={t("infra.hostMihomoIpVersion")}>
                <Input value={form.mihomo_ip_version || ""} onChange={(e) => set("mihomo_ip_version", e.target.value)} dir="ltr" placeholder="dual" />
              </Field>
              <Field label={t("infra.hostSortOrder")}>
                <Input type="number" value={form.sort_order ?? 0} onChange={(e) => set("sort_order", parseInt(e.target.value, 10) || 0)} dir="ltr" />
              </Field>
              <Field label={t("infra.hostFragment")}>
                <Input value={form.fragment_setting || ""} onChange={(e) => set("fragment_setting", e.target.value)} dir="ltr" />
              </Field>
              <Field label={t("infra.hostNoise")}>
                <Input value={form.noise_setting || ""} onChange={(e) => set("noise_setting", e.target.value)} dir="ltr" />
              </Field>
              <div className="sk-host-json-field">
                <Field label={t("infra.hostMuxParams")}>
                  <StructuredHostJsonFields kind="mux" value={form.mux_params || ""} onChange={(v) => set("mux_params", v)} />
                </Field>
              </div>
              <div className="sk-host-json-field">
                <Field label={t("infra.hostSockoptParams")}>
                  <StructuredHostJsonFields kind="sockopt" value={form.sockopt_params || ""} onChange={(v) => set("sockopt_params", v)} />
                </Field>
              </div>
              <div className="sk-host-json-field">
                <Field label={t("infra.hostFinalMask")}>
                  <StructuredHostJsonFields kind="final_mask" value={form.final_mask || ""} onChange={(v) => set("final_mask", v)} />
                </Field>
              </div>
              <div className="sk-host-span-2">
                <Field label={t("infra.hostExternalProxy")}>
                  <ExternalProxyEditor
                    value={form.external_proxy || ""}
                    onChange={(v) => set("external_proxy", v)}
                  />
                </Field>
              </div>
              <div className="sk-host-toggle-row">
                <Toggle on={!!form.random_user_agent} onChange={(v) => set("random_user_agent", v)} label={t("infra.hostRandomUa")} />
                <span className="sk-host-toggle-label">{t("infra.hostRandomUa")}</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
};
