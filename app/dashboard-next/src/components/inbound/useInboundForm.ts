"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useForm, type UseFormReturn } from "react-hook-form";
import { api } from "@/panel/api/client";
import { generateRealityKeypair, randomShortId } from "@/panel/lib/xrayHelpers";
import { buildXrayInbound } from "./buildXrayInbound";
import {
  defaultInboundFormState,
  findProtocolDef,
  getActiveSteps,
  isKnownProtocol,
  type InboundFormState,
  type ProtocolDefinition,
  type StepId,
} from "./types";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const PORT_RE = /^(\d{1,5})(-\d{1,5})?(,\d{1,5}(-\d{1,5})?)*$/;

function isValidPort(port: string): boolean {
  const s = port.trim();
  if (!s) return false;
  if (/^\d+$/.test(s)) {
    const n = parseInt(s, 10);
    return n >= 1 && n <= 65535;
  }
  return PORT_RE.test(s);
}

function validateStep(
  stepId: StepId,
  values: InboundFormState,
  protocols: ProtocolDefinition[],
): Record<string, string> {
  const errors: Record<string, string> = {};
  const def = findProtocolDef(protocols, values.protocol);
  const known = isKnownProtocol(protocols, values.protocol);

  if (stepId === "basics") {
    if (!values.basics.remark.trim()) errors["basics.remark"] = "Remark is required";
    if (values.protocol !== "tun") {
      if (!isValidPort(values.basics.port)) errors["basics.port"] = "Invalid port format";
    }
  }

  if (stepId === "settings") {
    if (!known) {
      try {
        JSON.stringify(values.customSettings);
      } catch {
        errors["customSettings"] = "Invalid JSON settings";
      }
      return errors;
    }

    switch (values.protocol) {
      case "vless":
        break;
      case "vmess": {
        if (!values.vmess.clients.some((u) => u.id.trim()))
          errors["vmess.clients"] = "At least one user required";
        break;
      }
      case "trojan": {
        if (!values.trojan.clients.some((u) => u.password.trim()))
          errors["trojan.clients"] = "At least one user with password required";
        break;
      }
      case "shadowsocks": {
        if (values.shadowsocks.method.startsWith("2022-blake3") && !values.shadowsocks.password.trim())
          errors["shadowsocks.password"] = "Password required for SS-2022";
        break;
      }
      case "wireguard":
      case "amneziawg": {
        if (!values.wireguard.secretKey.trim())
          errors["wireguard.secretKey"] = "Server private key required";
        if (!values.wireguard.peers.some((p) => p.publicKey.trim()))
          errors["wireguard.peers"] = "At least one peer required";
        if (values.protocol === "amneziawg") {
          try {
            JSON.parse(values.amneziaExtraJson);
          } catch {
            errors["amneziaExtraJson"] = "Invalid JSON";
          }
        }
        break;
      }
      case "hysteria": {
        if (!values.hysteria2.users.some((u) => u.auth.trim()))
          errors["hysteria2.users"] = "At least one user with auth required";
        break;
      }
      case "tun": {
        if (!values.tun.name.trim()) errors["tun.name"] = "Interface name required";
        if (!values.tun.gateway.length) errors["tun.gateway"] = "At least one gateway prefix required";
        break;
      }
      case "dokodemo-door": {
        if (values.dokodemo.tunnelRewriteEnabled) {
          if (!values.dokodemo.rewriteAddress.trim()) errors["dokodemo.rewriteAddress"] = "Rewrite address required";
        } else {
          if (!values.dokodemo.address.trim()) errors["dokodemo.address"] = "Address required";
          if (!values.dokodemo.port) errors["dokodemo.port"] = "Port required";
        }
        break;
      }
      default:
        break;
    }
  }

  if (stepId === "stream" && def?.hasStream) {
    const net = values.network;
    if (net === "ws" && !values.wsSettings.path.startsWith("/"))
      errors["wsSettings.path"] = "Path must start with /";
    if (net === "xhttp" && !values.xhttpSettings.path.startsWith("/"))
      errors["xhttpSettings.path"] = "Path must start with /";
    if (net === "httpupgrade" && !values.httpupgradeSettings.path.startsWith("/"))
      errors["httpupgradeSettings.path"] = "Path must start with /";
    if (net === "grpc" && !values.grpcSettings.serviceName.trim())
      errors["grpcSettings.serviceName"] = "Service name required";
  }

  if (stepId === "security" && def?.hasSecurity) {
    if (values.security === "tls") {
      const hasCert = values.tlsSettings.certificates.some(
        (c) =>
          (!c.pemMode && c.certificateFile && c.keyFile) ||
          (c.certificate.some(Boolean) && c.key.some(Boolean)),
      );
      if (!hasCert) errors["tlsSettings.certificates"] = "At least one certificate required";
    }
    if (values.security === "reality") {
      const r = values.realitySettings;
      if (!r.target.trim()) errors["realitySettings.target"] = "Target required";
      if (!r.privateKey.trim()) errors["realitySettings.privateKey"] = "Private key required";
      if (!r.serverNames.length) errors["realitySettings.serverNames"] = "At least one server name";
      if (!r.shortIds.length) errors["realitySettings.shortIds"] = "At least one short ID";
    }
  }

  return errors;
}

function stepHasErrors(
  stepId: StepId,
  values: InboundFormState,
  protocols: ProtocolDefinition[],
): boolean {
  if (stepId === "review") return false;
  return Object.keys(validateStep(stepId, values, protocols)).length > 0;
}

export function generateUuid(): string {
  return crypto.randomUUID();
}

export function generateShortId(): string {
  return randomShortId();
}

export function generatePassword(bytes = 16): string {
  const arr = new Uint8Array(bytes);
  crypto.getRandomValues(arr);
  return btoa(String.fromCharCode(...arr))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/** SS-2022 server PSK — standard base64 (Xray rejects URL-safe alphabet). */
export function generateSs2022Key(bytes: number): string {
  const arr = new Uint8Array(bytes);
  crypto.getRandomValues(arr);
  return btoa(String.fromCharCode(...arr));
}

export function ssPasswordLength(method: string): number {
  if (method === "2022-blake3-aes-128-gcm") return 16;
  if (method.startsWith("2022-blake3")) return 32;
  return 16;
}

async function fetchRealityKeys(): Promise<{ privateKey: string; publicKey: string }> {
  try {
    const data = await api.post<{ privateKey: string; publicKey: string }>(
      "/core/reality/keypair",
    );
    if (data?.privateKey && data?.publicKey) return data;
  } catch {
    /* fall through to browser WebCrypto */
  }
  return generateRealityKeypair();
}

export function fieldError(errors: Record<string, string>, path: string): string | undefined {
  return errors[path];
}

export interface UseInboundFormReturn {
  form: UseFormReturn<InboundFormState>;
  activeSteps: StepId[];
  stepIndex: number;
  currentStepId: StepId;
  stepErrors: Record<string, string>;
  protocolDef: ProtocolDefinition | undefined;
  isRealityIncompatible: boolean;
  isHysteria: boolean;
  setStepIndex: (i: number) => void;
  setProtocol: (id: string, skipConfirm?: boolean) => boolean;
  setNetwork: (n: InboundFormState["network"]) => void;
  setSecurity: (s: InboundFormState["security"]) => void;
  generateRealityKeys: () => Promise<void>;
  getXrayJson: () => Record<string, unknown>;
  validateAll: () => { ok: boolean; firstErrorIndex: number };
  resetValidation: () => void;
  errorStepIndices: number[];
  hasSettingsData: () => boolean;
}

export function useInboundForm(
  protocols: ProtocolDefinition[],
  initial?: Partial<InboundFormState>,
): UseInboundFormReturn {
  const [stepIndex, setStepIndex] = useState(0);
  const [stepErrors, setStepErrors] = useState<Record<string, string>>({});

  const form = useForm<InboundFormState>({
    defaultValues: { ...defaultInboundFormState(), ...initial },
    mode: "onChange",
  });

  const values = form.watch();
  const protocolDef = findProtocolDef(protocols, values.protocol);
  const activeSteps = useMemo(
    () => getActiveSteps(protocolDef),
    [protocolDef],
  );
  const activeStepsRef = useRef(activeSteps);
  activeStepsRef.current = activeSteps;
  const currentStepId = activeSteps[stepIndex] ?? "review";
  const isRealityIncompatible =
    values.security === "reality" &&
    !["raw", "xhttp", "grpc"].includes(values.network);
  const isHysteria = values.protocol === "hysteria";

  const [showAllErrors, setShowAllErrors] = useState(false);

  const errorStepIndices = useMemo(() => {
    if (!showAllErrors) return [];
    return activeSteps
      .map((stepId, i) => (stepHasErrors(stepId, values, protocols) ? i : -1))
      .filter((i) => i >= 0);
  }, [showAllErrors, activeSteps, values, protocols]);

  useEffect(() => {
    if (stepIndex >= activeSteps.length) {
      setStepIndex(Math.max(0, activeSteps.length - 1));
    }
  }, [activeSteps.length, stepIndex, setStepIndex]);

  useEffect(() => {
    if (!protocolDef?.hasSecurity && values.security !== "none") {
      form.setValue("security", "none");
    }
    if (values.protocol === "shadowsocks" && values.security === "reality") {
      form.setValue("security", "none");
    }
  }, [protocolDef?.hasSecurity, values.protocol, values.security, form]);

  const goToStep = useCallback((i: number) => {
    setStepIndex((prev) => {
      const max = activeStepsRef.current.length - 1;
      return Math.max(0, Math.min(i, max));
    });
  }, []);

  const hasSettingsData = useCallback((): boolean => {
    const v = form.getValues();
    if (v.protocol === "vless")
      return v.vless.decryption !== "none" || v.vless.encryption !== "none" || v.vless.fallbacks.length > 0;
    if (v.protocol === "vmess") return v.vmess.clients.some((u) => u.id.trim());
    if (v.protocol === "trojan") return v.trojan.clients.some((u) => u.password.trim());
    if (v.protocol === "shadowsocks") return !!v.shadowsocks.password.trim();
    if (v.protocol === "wireguard" || v.protocol === "amneziawg")
      return !!v.wireguard.secretKey.trim();
    if (v.protocol === "hysteria") return v.hysteria2.users.some((u) => u.auth.trim());
    if (v.protocol === "tun") return !!v.tun.name.trim();
    if (v.protocol === "dokodemo-door") {
      return v.dokodemo.tunnelRewriteEnabled
        ? !!v.dokodemo.rewriteAddress.trim()
        : !!v.dokodemo.address.trim();
    }
    return Object.keys(v.customSettings).length > 0;
  }, [form]);

  const resetProtocolSettings = useCallback(
    (protocol: string) => {
      const defaults = defaultInboundFormState();
      form.setValue("vless", defaults.vless);
      form.setValue("vmess", defaults.vmess);
      form.setValue("trojan", defaults.trojan);
      form.setValue("shadowsocks", defaults.shadowsocks);
      form.setValue("http", defaults.http);
      form.setValue("socks", defaults.socks);
      form.setValue("wireguard", defaults.wireguard);
      form.setValue("hysteria2", defaults.hysteria2);
      form.setValue("tun", defaults.tun);
      form.setValue("dokodemo", defaults.dokodemo);
      form.setValue("amneziaExtraJson", defaults.amneziaExtraJson);
      form.setValue("customSettings", defaults.customSettings);
      form.setValue("protocol", protocol);
      if (protocol === "hysteria") form.setValue("security", "tls");
    },
    [form],
  );

  const setProtocol = useCallback(
    (id: string, skipConfirm = false): boolean => {
      if (!skipConfirm && hasSettingsData() && id !== form.getValues().protocol) {
        if (!window.confirm("Changing protocol will reset protocol settings. Continue?"))
          return false;
      }
      const prev = form.getValues();
      resetProtocolSettings(id);
      form.setValue("basics", prev.basics);
      form.setValue("network", prev.network);
      form.setValue("rawSettings", prev.rawSettings);
      form.setValue("sockoptSettings", prev.sockoptSettings);
      form.setValue("tcpMasks", prev.tcpMasks);
      form.setValue("wsSettings", prev.wsSettings);
      form.setValue("grpcSettings", prev.grpcSettings);
      form.setValue("xhttpSettings", prev.xhttpSettings);
      form.setValue("httpupgradeSettings", prev.httpupgradeSettings);
      form.setValue("mkcpSettings", prev.mkcpSettings);
      form.setValue("quicSettings", prev.quicSettings);
      form.setValue("httpTransportSettings", prev.httpTransportSettings);
      const nextDef = findProtocolDef(protocols, id);
      const defaults = defaultInboundFormState();
      if (!nextDef?.hasSecurity) {
        form.setValue("security", "none");
        form.setValue("tlsSettings", defaults.tlsSettings);
        form.setValue("realitySettings", defaults.realitySettings);
      } else if (id === "hysteria") {
        form.setValue("security", "tls");
        form.setValue("tlsSettings", prev.tlsSettings);
        form.setValue("realitySettings", prev.realitySettings);
      } else if (id === "shadowsocks" && prev.security === "reality") {
        form.setValue("security", "none");
        form.setValue("tlsSettings", prev.tlsSettings);
        form.setValue("realitySettings", defaults.realitySettings);
      } else {
        form.setValue("security", prev.security);
        form.setValue("tlsSettings", prev.tlsSettings);
        form.setValue("realitySettings", prev.realitySettings);
      }
      if (!nextDef?.hasStream) {
        form.setValue("network", defaults.network);
      }
      form.setValue("sniffing", prev.sniffing);
      return true;
    },
    [form, hasSettingsData, resetProtocolSettings, protocols],
  );

  const setNetwork = useCallback(
    (n: InboundFormState["network"]) => {
      const defaults = defaultInboundFormState();
      if (n === "quic") {
        form.setValue("network", "xhttp");
        form.setValue("xhttpSettings", { ...defaults.xhttpSettings, mode: "stream-one", path: "/" });
        form.setValue("security", "tls");
        const curTls = form.getValues("tlsSettings");
        const alpn = curTls.alpn.includes("h3")
          ? curTls.alpn
          : ["h3", ...curTls.alpn.filter((a) => a !== "h3")];
        form.setValue("tlsSettings", { ...defaults.tlsSettings, ...curTls, alpn });
        form.setValue("rawSettings", defaults.rawSettings);
        form.setValue("wsSettings", defaults.wsSettings);
        form.setValue("grpcSettings", defaults.grpcSettings);
        form.setValue("httpupgradeSettings", defaults.httpupgradeSettings);
        form.setValue("mkcpSettings", defaults.mkcpSettings);
        form.setValue("quicSettings", defaults.quicSettings);
        form.setValue("httpTransportSettings", defaults.httpTransportSettings);
        return;
      }
      form.setValue("network", n);
      form.setValue("rawSettings", defaults.rawSettings);
      form.setValue("wsSettings", defaults.wsSettings);
      form.setValue("grpcSettings", defaults.grpcSettings);
      form.setValue("xhttpSettings", defaults.xhttpSettings);
      form.setValue("httpupgradeSettings", defaults.httpupgradeSettings);
      form.setValue("mkcpSettings", defaults.mkcpSettings);
      form.setValue("quicSettings", defaults.quicSettings);
      form.setValue("httpTransportSettings", defaults.httpTransportSettings);
    },
    [form],
  );

  const setSecurity = useCallback(
    (s: InboundFormState["security"]) => {
      const proto = form.getValues().protocol;
      const def = findProtocolDef(protocols, proto);
      if (!def?.hasSecurity) return;
      if (proto === "shadowsocks" && s === "reality") return;
      if (proto === "hysteria" && s !== "tls") return;
      const prev = form.getValues("security");
      form.setValue("security", s);
      const defaults = defaultInboundFormState();
      if (s === "tls" && prev !== "tls") {
        form.setValue("tlsSettings", defaults.tlsSettings);
      }
      if (s === "reality" && prev !== "reality") {
        const cur = form.getValues("realitySettings");
        form.setValue("realitySettings", {
          ...defaults.realitySettings,
          ...cur,
          target: cur.target.trim() || defaults.realitySettings.target,
          serverNames: cur.serverNames.length ? cur.serverNames : defaults.realitySettings.serverNames,
        });
      }
    },
    [form, protocols],
  );

  const generateRealityKeysHandler = useCallback(async () => {
    if (!findProtocolDef(protocols, form.getValues().protocol)?.hasSecurity) return;
    try {
      const keys = await fetchRealityKeys();
      const cur = form.getValues("realitySettings");
      form.setValue("realitySettings.privateKey", keys.privateKey, {
        shouldDirty: true,
        shouldValidate: true,
      });
      form.setValue("realitySettings.publicKey", keys.publicKey, {
        shouldDirty: true,
        shouldValidate: true,
      });
      if (!cur.target.trim()) {
        form.setValue("realitySettings.target", "www.cloudflare.com:443");
      }
      if (!cur.serverNames.length) {
        form.setValue("realitySettings.serverNames", ["www.cloudflare.com"]);
      }
      if (!form.getValues("realitySettings.shortIds").length) {
        form.setValue("realitySettings.shortIds", [generateShortId()]);
      }
      form.setValue("security", "reality");
      setStepErrors((prev) => {
        if (!prev["realitySettings.privateKey"]) return prev;
        const next = { ...prev };
        delete next["realitySettings.privateKey"];
        return next;
      });
    } catch {
      setStepErrors((prev) => ({
        ...prev,
        "realitySettings.privateKey": "Failed to generate keys",
      }));
    }
  }, [form, protocols]);

  const resetValidation = useCallback(() => {
    setShowAllErrors(false);
    setStepErrors({});
  }, []);

  const validateAll = useCallback((): { ok: boolean; firstErrorIndex: number } => {
    const v = form.getValues();
    let allErrors: Record<string, string> = {};
    let firstErrorIndex = -1;
    for (let i = 0; i < activeSteps.length; i++) {
      const stepId = activeSteps[i];
      if (stepId === "review") continue;
      const errs = validateStep(stepId, v, protocols);
      if (Object.keys(errs).length) {
        allErrors = { ...allErrors, ...errs };
        if (firstErrorIndex < 0) firstErrorIndex = i;
      }
    }
    setShowAllErrors(true);
    setStepErrors(allErrors);
    return { ok: Object.keys(allErrors).length === 0, firstErrorIndex };
  }, [form, activeSteps, protocols]);

  const getXrayJson = useCallback(
    () => buildXrayInbound(form.getValues(), protocols),
    [form, protocols],
  );

  return {
    form,
    activeSteps,
    stepIndex,
    currentStepId,
    stepErrors,
    protocolDef,
    isRealityIncompatible,
    isHysteria,
    setStepIndex: goToStep,
    setProtocol,
    setNetwork,
    setSecurity,
    generateRealityKeys: generateRealityKeysHandler,
    getXrayJson,
    validateAll,
    resetValidation,
    errorStepIndices,
    hasSettingsData,
  };
}
