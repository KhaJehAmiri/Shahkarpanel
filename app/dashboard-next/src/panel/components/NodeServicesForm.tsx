import React, { FC, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useApp } from "../context/AppContext";
import { isIranNode } from "../lib/region";
import { Callout, Field, Input, Select } from "./ui";

export type NodeServicesState = {
  core_kind: "xray" | "wireguard";
  enable_plain_wg: boolean;
  enable_awg: boolean;
  enable_hysteria2: boolean;
  enable_tuic: boolean;
  enable_anytls: boolean;
  makeTunnel: boolean;
  tunnelPort: string;
  tls_mode: "self_signed" | "letsencrypt";
  le_target: string;
  le_email: string;
  le_kind: string;
};

export function defaultNodeServices(coreKind: "xray" | "wireguard" = "xray"): NodeServicesState {
  return {
    core_kind: coreKind,
    enable_plain_wg: coreKind === "wireguard",
    enable_awg: false,
    enable_hysteria2: coreKind === "xray",
    enable_tuic: false,
    enable_anytls: false,
    makeTunnel: false,
    tunnelPort: "443",
    tls_mode: "self_signed",
    le_target: "",
    le_email: "",
    le_kind: "auto",
  };
}

/** Map UI state → POST /nodes/provision body fields. */
export function buildProvisionServicesPayload(
  s: NodeServicesState,
  address: string,
): Record<string, unknown> {
  const wantsQuic = s.enable_hysteria2 || s.enable_tuic || s.enable_anytls;
  const leTarget = (s.le_target.trim() || address.trim()) || null;
  const isWg = s.core_kind === "wireguard";
  return {
    enable_hysteria2: wantsQuic,
    enable_tuic: s.enable_tuic,
    enable_anytls: s.enable_anytls,
    tls_mode: wantsQuic ? s.tls_mode : "none",
    tls_self_signed: wantsQuic && s.tls_mode === "self_signed",
    le_target: wantsQuic && s.tls_mode === "letsencrypt" ? leTarget : null,
    le_email: wantsQuic && s.tls_mode === "letsencrypt" && s.le_email.trim() ? s.le_email.trim() : null,
    le_kind: s.le_kind,
    create_tunnel: s.makeTunnel,
    tunnel_port: parseInt(s.tunnelPort, 10) || 443,
    enable_plain_wg: isWg ? s.enable_plain_wg : true,
    enable_awg_wg: isWg ? s.enable_awg : false,
    enable_plain_wg_on_xray: !isWg && s.enable_plain_wg,
    enable_awg_on_xray: !isWg && s.enable_awg,
  };
}

const ServiceOption: FC<{
  checked: boolean;
  onChange?: (checked: boolean) => void;
  label: string;
  hint?: string;
  locked?: boolean;
  className?: string;
}> = ({ checked, onChange, label, hint, locked, className }) => (
  <label className={["nx-add-node-option", locked && "is-locked", className].filter(Boolean).join(" ")}>
    <input
      type="checkbox"
      checked={checked}
      disabled={locked}
      onChange={onChange ? (e) => onChange(e.target.checked) : undefined}
    />
    <span className="nx-add-node-option-text">
      <span className="nx-add-node-option-label">{label}</span>
      {hint && <span className="nx-add-node-option-hint">{hint}</span>}
    </span>
  </label>
);

export const NodeServicesForm: FC<{
  state: NodeServicesState;
  setState: (patch: Partial<NodeServicesState>) => void;
  serverAddress?: string;
  region?: string;
}> = ({ state: s, setState, serverAddress = "", region = "" }) => {
  const { t } = useTranslation();
  const { isEnabled } = useApp();
  const wantsQuic = s.enable_hysteria2 || s.enable_tuic || s.enable_anytls;
  const showTunnel = isEnabled("tunneling");

  useEffect(() => {
    if (s.tls_mode === "letsencrypt" && !s.le_target.trim() && serverAddress.trim()) {
      setState({ le_target: serverAddress.trim() });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverAddress, s.tls_mode]);

  const isWg = s.core_kind === "wireguard";

  return (
    <section className="nx-add-node-section" aria-labelledby="add-node-services">
      <h3 className="nx-add-node-section-title" id="add-node-services">{t("infra.servicesTitle")}</h3>
      <div className="nx-add-node-services-panel">
        <p className="nx-add-node-services-lead">{t("infra.servicesHint")}</p>

        <div className="nx-add-node-services-grid">
          {isWg ? (
            <>
              <ServiceOption
                checked={s.enable_plain_wg}
                onChange={(v) => setState({ enable_plain_wg: v })}
                label={t("infra.enablePlainWg")}
              />
              <ServiceOption
                checked={s.enable_awg}
                onChange={(v) => setState({ enable_awg: v })}
                label={t("infra.enableAwgWg")}
              />
            </>
          ) : (
            <>
              <ServiceOption
                checked
                locked
                label={t("infra.serviceXray")}
                hint={t("infra.serviceAlways")}
              />
              <ServiceOption
                checked={s.enable_plain_wg}
                onChange={(v) => setState({ enable_plain_wg: v })}
                label={t("infra.enableWgOnXray")}
              />
              <ServiceOption
                checked={s.enable_awg}
                onChange={(v) => setState({ enable_awg: v })}
                label={t("infra.enableAwgOnXray")}
              />
            </>
          )}

          <ServiceOption
            checked={s.enable_hysteria2}
            onChange={(v) => setState({ enable_hysteria2: v })}
            label={t("infra.enableHy2")}
          />
          <ServiceOption
            checked={s.enable_tuic}
            onChange={(v) => setState({ enable_tuic: v })}
            label={t("infra.enableTuic")}
          />
          <ServiceOption
            checked={s.enable_anytls}
            onChange={(v) => setState({ enable_anytls: v })}
            label={t("infra.enableAnytls")}
          />

          {showTunnel && (
            <div className="nx-add-node-tunnel-block">
              <ServiceOption
                checked={s.makeTunnel}
                onChange={(v) => setState({ makeTunnel: v })}
                label={t("infra.makeTunnelWithPanel")}
                className="span-2"
              />
              {s.makeTunnel && (
                <>
                  <Callout tone="info" className="compact">
                    {isIranNode(region) ? t("infra.makeTunnelHintIran") : t("infra.makeTunnelHintForeign")}
                  </Callout>
                  <Field label={t("infra.tunnelPort")} hint={t("infra.tunnelPortHint")}>
                    <Input
                      type="number"
                      value={s.tunnelPort}
                      onChange={(e) => setState({ tunnelPort: e.target.value })}
                    />
                  </Field>
                </>
              )}
            </div>
          )}
        </div>

        {wantsQuic && (
          <div className="nx-add-node-ssl-panel">
            <div className="nx-add-node-section-title" style={{ textTransform: "none", letterSpacing: 0, fontSize: 13, color: "var(--nx-text)" }}>
              {t("infra.sslTitle")}
            </div>
            <p className="nx-add-node-services-lead">{t("infra.sslHint")}</p>
            <div className="nx-add-node-ssl-radios">
              <label className="nx-add-node-option" style={{ flex: "1 1 200px" }}>
                <input
                  type="radio"
                  name="tls_mode"
                  checked={s.tls_mode === "self_signed"}
                  onChange={() => setState({ tls_mode: "self_signed" })}
                />
                <span className="nx-add-node-option-text">
                  <span className="nx-add-node-option-label">{t("infra.sslSelfSigned")}</span>
                </span>
              </label>
              <label className="nx-add-node-option" style={{ flex: "1 1 200px" }}>
                <input
                  type="radio"
                  name="tls_mode"
                  checked={s.tls_mode === "letsencrypt"}
                  onChange={() => setState({ tls_mode: "letsencrypt" })}
                />
                <span className="nx-add-node-option-text">
                  <span className="nx-add-node-option-label">{t("infra.sslLetsEncrypt")}</span>
                </span>
              </label>
            </div>
            {s.tls_mode === "letsencrypt" && (
              <div className="nx-form-grid" style={{ marginTop: 2 }}>
                <Field label={t("infra.leTarget")}>
                  <Input
                    value={s.le_target}
                    onChange={(e) => setState({ le_target: e.target.value })}
                    placeholder={serverAddress || "vpn.example.com"}
                  />
                </Field>
                <Field label={t("infra.leKind")}>
                  <Select value={s.le_kind} onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setState({ le_kind: e.target.value })}>
                    <option value="auto">{t("infra.leKindAuto")}</option>
                    <option value="domain">{t("infra.leKindDomain")}</option>
                    <option value="ip">{t("infra.leKindIp")}</option>
                  </Select>
                </Field>
                <div className="span-2">
                  <Field label={t("singbox.leEmail")}>
                    <Input
                      value={s.le_email}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => setState({ le_email: e.target.value })}
                      type="email"
                    />
                  </Field>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
};
