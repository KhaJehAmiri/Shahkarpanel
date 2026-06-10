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
  const wantsQuic = s.enable_hysteria2 || s.enable_tuic;
  const leTarget = (s.le_target.trim() || address.trim()) || null;
  const isWg = s.core_kind === "wireguard";
  return {
    enable_hysteria2: wantsQuic,
    enable_tuic: s.enable_tuic,
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

export const NodeServicesForm: FC<{
  state: NodeServicesState;
  setState: (patch: Partial<NodeServicesState>) => void;
  serverAddress?: string;
  region?: string;
}> = ({ state: s, setState, serverAddress = "", region = "" }) => {
  const { t } = useTranslation();
  const { isEnabled } = useApp();
  const wantsQuic = s.enable_hysteria2 || s.enable_tuic;
  const showTunnel = isEnabled("tunneling");

  useEffect(() => {
    if (s.tls_mode === "letsencrypt" && !s.le_target.trim() && serverAddress.trim()) {
      setState({ le_target: serverAddress.trim() });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverAddress, s.tls_mode]);

  const isWg = s.core_kind === "wireguard";

  return (
    <div className="span-2 nx-stack" style={{ gap: 10 }}>
      <div className="nx-faint" style={{ fontSize: 12, fontWeight: 600 }}>{t("infra.servicesTitle")}</div>
      <div className="nx-faint" style={{ fontSize: 12 }}>{t("infra.servicesHint")}</div>

      {isWg && (
        <>
          <label className="nx-row" style={{ gap: 8, fontSize: 13 }}>
            <input
              type="checkbox"
              checked={s.enable_plain_wg}
              onChange={(e) => setState({ enable_plain_wg: e.target.checked })}
            />
            {t("infra.enablePlainWg")}
          </label>
          <label className="nx-row" style={{ gap: 8, fontSize: 13 }}>
            <input
              type="checkbox"
              checked={s.enable_awg}
              onChange={(e) => setState({ enable_awg: e.target.checked })}
            />
            {t("infra.enableAwgWg")}
          </label>
        </>
      )}

      {!isWg && (
        <>
          <label className="nx-row" style={{ gap: 8, fontSize: 13 }}>
            <input type="checkbox" checked disabled />
            <span>{t("infra.serviceXray")}</span>
            <span className="nx-faint" style={{ fontSize: 11 }}>({t("infra.serviceAlways")})</span>
          </label>
          <label className="nx-row" style={{ gap: 8, fontSize: 13 }}>
            <input
              type="checkbox"
              checked={s.enable_plain_wg}
              onChange={(e) => setState({ enable_plain_wg: e.target.checked })}
            />
            {t("infra.enableWgOnXray")}
          </label>
          <label className="nx-row" style={{ gap: 8, fontSize: 13 }}>
            <input
              type="checkbox"
              checked={s.enable_awg}
              onChange={(e) => setState({ enable_awg: e.target.checked })}
            />
            {t("infra.enableAwgOnXray")}
          </label>
        </>
      )}

      <label className="nx-row" style={{ gap: 8, fontSize: 13 }}>
        <input
          type="checkbox"
          checked={s.enable_hysteria2}
          onChange={(e) => setState({ enable_hysteria2: e.target.checked })}
        />
        {t("infra.enableHy2")}
      </label>
      <label className="nx-row" style={{ gap: 8, fontSize: 13 }}>
        <input
          type="checkbox"
          checked={s.enable_tuic}
          onChange={(e) => setState({ enable_tuic: e.target.checked })}
        />
        {t("infra.enableTuic")}
      </label>

      {showTunnel && (
        <div className="nx-stack" style={{ gap: 8 }}>
          <label className="nx-row" style={{ gap: 8, fontSize: 13 }}>
            <input
              type="checkbox"
              checked={s.makeTunnel}
              onChange={(e) => setState({ makeTunnel: e.target.checked })}
            />
            {t("infra.makeTunnelWithPanel")}
          </label>
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

      {wantsQuic && (
        <div className="nx-stack" style={{ gap: 8, marginTop: 4, paddingTop: 10, borderTop: "1px solid var(--nx-border)" }}>
          <div className="nx-faint" style={{ fontSize: 12, fontWeight: 600 }}>{t("infra.sslTitle")}</div>
          <div className="nx-faint" style={{ fontSize: 12 }}>{t("infra.sslHint")}</div>
          <div className="nx-row" style={{ gap: 16, flexWrap: "wrap" }}>
            <label className="nx-row" style={{ gap: 6, fontSize: 13 }}>
              <input
                type="radio"
                name="tls_mode"
                checked={s.tls_mode === "self_signed"}
                onChange={() => setState({ tls_mode: "self_signed" })}
              />
              {t("infra.sslSelfSigned")}
            </label>
            <label className="nx-row" style={{ gap: 6, fontSize: 13 }}>
              <input
                type="radio"
                name="tls_mode"
                checked={s.tls_mode === "letsencrypt"}
                onChange={() => setState({ tls_mode: "letsencrypt" })}
              />
              {t("infra.sslLetsEncrypt")}
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
  );
};
