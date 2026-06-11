import { ChangeEvent, FC, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ADVANCED_INBOUND_PROTOCOLS,
  FINGERPRINTS,
  KCP_HEADERS,
  NETWORKS,
  PRODUCT_INBOUND_PROTOCOLS,
  PROXY_PROTOCOLS,
  SECURITIES,
  SNIFF_OVERRIDES,
  SS_2022_METHODS,
  SS_LEGACY_METHODS,
  SS_METHODS,
  SS_NETWORKS,
  VLESS_FLOWS,
  defaultInboundForm,
  emptyFallback,
  generateRealityKeypair,
  inboundToForm,
  isSs2022,
  randomShortId,
  supportsFallback,
  supportsStream,
  type FallbackForm,
  type InboundForm,
  buildInboundFromForm,
} from "../../lib/xrayHelpers";
import { api } from "../../api/client";
import { Button, Callout, Checkbox, CopyButton, Field, Input, Modal, Select, useToast } from "../ui";

const Section: FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <div>
    <div style={{ fontSize: 12, fontWeight: 700, color: "var(--nx-muted)", marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.04em" }}>
      {title}
    </div>
    <div className="nx-stack" style={{ gap: 12 }}>{children}</div>
  </div>
);

export const InboundEditor: FC<{
  initial: Record<string, unknown> | null;
  allInbounds: Record<string, unknown>[];
  onClose: () => void;
  onApply: (built: Record<string, unknown>, originalTag?: string) => void;
}> = ({ initial, allInbounds, onClose, onApply }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [f, setF] = useState<InboundForm>(initial ? inboundToForm(initial) : defaultInboundForm());
  const [genKeys, setGenKeys] = useState(false);
  const [genWgKeys, setGenWgKeys] = useState(false);
  const originalTag = initial ? String(initial.tag) : undefined;

  const upd = (k: keyof InboundForm) => (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    setF((prev) => ({ ...prev, [k]: e.target.value }));
  };

  const toggle = (k: keyof InboundForm) => () =>
    setF((prev) => ({ ...prev, [k]: !prev[k as keyof InboundForm] }));

  const addFallback = () =>
    setF((prev) => ({ ...prev, fallbacks: [...prev.fallbacks, emptyFallback()] }));
  const removeFallback = (idx: number) =>
    setF((prev) => ({ ...prev, fallbacks: prev.fallbacks.filter((_, i) => i !== idx) }));
  const updFallback = (idx: number, key: keyof FallbackForm) =>
    (e: ChangeEvent<HTMLInputElement>) => {
      const value = e.target.value;
      setF((prev) => ({
        ...prev,
        fallbacks: prev.fallbacks.map((fb, i) => (i === idx ? { ...fb, [key]: value } : fb)),
      }));
    };

  const setProtocol = (p: string) => {
    setF((prev) => ({
      ...defaultInboundForm(),
      tag: prev.tag,
      listen: prev.listen,
      port: prev.port,
      protocol: p,
    }));
  };

  const genReality = async () => {
    setGenKeys(true);
    try {
      const { privateKey, publicKey } = await generateRealityKeypair();
      setF((prev) => ({
        ...prev,
        realityPrivateKey: privateKey,
        realityPublicKey: publicKey,
        realityShortIds: prev.realityShortIds || randomShortId(),
        security: "reality",
      }));
      toast.push(t("inbounds.realityKeysGenerated"), "success");
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : "Keygen failed", "error");
    } finally {
      setGenKeys(false);
    }
  };

  const genWireGuard = async () => {
    setGenWgKeys(true);
    try {
      const kp = await api.get<{ privateKey: string; publicKey: string }>("/core/wireguard/keypair");
      setF((prev) => ({ ...prev, wgSecretKey: kp.privateKey }));
      toast.push(t("inbounds.wgKeysGenerated"), "success");
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : "Keygen failed", "error");
    } finally {
      setGenWgKeys(false);
    }
  };

  const submit = async () => {
    const clash = allInbounds.some(
      (i) => i.tag !== originalTag && (String(i.tag) === f.tag.trim() || String(i.port) === f.port),
    );
    if (clash) {
      toast.push(t("xray.tagPortConflict"), "error");
      return;
    }
    if (f.security === "reality" && !f.realityPrivateKey.trim()) {
      toast.push(t("inbounds.realityKeyRequired"), "error");
      return;
    }
    let form = f;
    if ((f.protocol === "wireguard" || f.protocol === "amneziawg") && !f.wgSecretKey.trim()) {
      try {
        const kp = await api.get<{ privateKey: string; publicKey: string }>("/core/wireguard/keypair");
        form = { ...f, wgSecretKey: kp.privateKey };
      } catch (e: unknown) {
        toast.push(e instanceof Error ? e.message : t("inbounds.wgKeygenFailed"), "error");
        return;
      }
    }
    onApply(buildInboundFromForm(form), originalTag);
  };

  const hasStream = supportsStream(f.protocol);
  const isProxy = PROXY_PROTOCOLS.includes(f.protocol as (typeof PROXY_PROTOCOLS)[number]);
  const showSecurity = hasStream && (isProxy || f.protocol === "shadowsocks");
  const isAdvanced = ADVANCED_INBOUND_PROTOCOLS.includes(
    f.protocol as (typeof ADVANCED_INBOUND_PROTOCOLS)[number],
  );
  const ssMethods = isSs2022(f.method) ? SS_2022_METHODS : SS_LEGACY_METHODS;

  return (
    <Modal
      open
      wide
      title={initial ? t("common.edit") : t("infra.addInbound")}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="primary" disabled={!f.tag || !f.port} onClick={submit}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      <div className="nx-stack" style={{ maxHeight: "72vh", overflow: "auto", gap: 20 }}>
        <Callout tone="info" title={t("inbounds.allProtocolsTitle")}>
          {t("inbounds.allProtocolsBody")}
        </Callout>
        {isAdvanced && (
          <Callout tone="warn" title={t("inbounds.advancedWarnTitle")}>
            {t("inbounds.advancedWarnBody")}
          </Callout>
        )}
        <Section title={t("inbounds.sectionBasic")}>
          <div className="nx-row" style={{ gap: 12, flexWrap: "wrap" }}>
            <Field label={t("infra.remark")}>
              <Input value={f.tag} onChange={upd("tag")} autoFocus placeholder="VLESS-Reality-443" />
            </Field>
            <Field label={t("xray.listen")}>
              <Input value={f.listen} onChange={upd("listen")} placeholder="0.0.0.0" />
            </Field>
            <Field label={t("infra.port")}>
              <Input type="number" value={f.port} onChange={upd("port")} />
            </Field>
          </div>
          <Field label={t("inbounds.protocol")}>
            <Select
              value={f.protocol}
              onChange={(e: ChangeEvent<HTMLSelectElement>) => setProtocol(e.target.value)}
            >
              <optgroup label={t("inbounds.productProtocols")}>
                {PRODUCT_INBOUND_PROTOCOLS.map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </optgroup>
              <optgroup label={t("inbounds.advancedProtocols")}>
                {ADVANCED_INBOUND_PROTOCOLS.map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </optgroup>
            </Select>
          </Field>
        </Section>

        {f.protocol === "dokodemo-door" && (
          <Section title={t("inbounds.sectionTunnel")}>
            <div className="nx-row" style={{ gap: 12, flexWrap: "wrap" }}>
              <Field label={t("infra.address")}>
                <Input value={f.tunnelAddress} onChange={upd("tunnelAddress")} placeholder="8.8.8.8" />
              </Field>
              <Field label={t("infra.port")}>
                <Input type="number" value={f.tunnelPort} onChange={upd("tunnelPort")} />
              </Field>
              <Field label={t("inbounds.network")}>
                <Input value={f.tunnelNetwork} onChange={upd("tunnelNetwork")} placeholder="tcp,udp" />
              </Field>
            </div>
            <label className="nx-row" style={{ gap: 8, cursor: "pointer" }}>
              <Checkbox checked={f.tunnelFollowRedirect} onChange={toggle("tunnelFollowRedirect")} />
              <span>{t("inbounds.followRedirect")}</span>
            </label>
          </Section>
        )}

        {f.protocol === "wireguard" && (
          <Section title="WireGuard">
            <div className="nx-row" style={{ gap: 8, marginBottom: 8 }}>
              <Button variant="ghost" size="sm" disabled={genWgKeys} onClick={genWireGuard}>
                {t("inbounds.generateWgKeys")}
              </Button>
            </div>
            <Field label={t("inbounds.wgSecretKey")}>
              <Input value={f.wgSecretKey} onChange={upd("wgSecretKey")} />
            </Field>
            <div className="nx-row" style={{ gap: 12, flexWrap: "wrap" }}>
              <Field label={t("inbounds.wgPeerKey")}>
                <Input value={f.wgPeerPublicKey} onChange={upd("wgPeerPublicKey")} />
              </Field>
              <Field label={t("inbounds.wgAllowedIPs")}>
                <Input value={f.wgAllowedIPs} onChange={upd("wgAllowedIPs")} />
              </Field>
              <Field label="MTU">
                <Input type="number" value={f.wgMtu} onChange={upd("wgMtu")} />
              </Field>
            </div>
          </Section>
        )}

        {f.protocol === "amneziawg" && (
          <Section title={t("inbounds.amneziaSection")}>
            <CalloutInline>{t("inbounds.amneziaInboundHint")}</CalloutInline>
            <div className="nx-row" style={{ gap: 8, marginBottom: 8 }}>
              <Button variant="ghost" size="sm" disabled={genWgKeys} onClick={genWireGuard}>
                {t("inbounds.generateWgKeys")}
              </Button>
            </div>
            <Field label={t("inbounds.wgSecretKey")}>
              <Input value={f.wgSecretKey} onChange={upd("wgSecretKey")} />
            </Field>
            <div className="nx-row" style={{ gap: 12, flexWrap: "wrap" }}>
              <Field label={t("inbounds.wgPeerKey")}>
                <Input value={f.wgPeerPublicKey} onChange={upd("wgPeerPublicKey")} />
              </Field>
              <Field label={t("inbounds.wgAllowedIPs")}>
                <Input value={f.wgAllowedIPs} onChange={upd("wgAllowedIPs")} />
              </Field>
              <Field label="MTU">
                <Input type="number" value={f.wgMtu} onChange={upd("wgMtu")} />
              </Field>
            </div>
          </Section>
        )}

        {f.protocol === "hysteria" && (
          <Section title={t("inbounds.hysteriaSection")}>
            <Field label={t("outbounds.hyAuth")}>
              <Input value={f.hyAuth} onChange={upd("hyAuth")} className="nx-mono" />
            </Field>
            <div className="nx-row" style={{ gap: 12, flexWrap: "wrap" }}>
              <Field label={t("outbounds.hyUp")}>
                <Input value={f.hyUp} onChange={upd("hyUp")} placeholder="100 mbps" />
              </Field>
              <Field label={t("outbounds.hyDown")}>
                <Input value={f.hyDown} onChange={upd("hyDown")} placeholder="100 mbps" />
              </Field>
              <Field label={t("outbounds.hyUdpIdle")}>
                <Input type="number" value={f.hyUdpIdleTimeout} onChange={upd("hyUdpIdleTimeout")} />
              </Field>
            </div>
            <div className="nx-row" style={{ gap: 12, flexWrap: "wrap" }}>
              <Field label="SNI">
                <Input value={f.sni} onChange={upd("sni")} />
              </Field>
              <Field label="ALPN">
                <Input value={f.alpn} onChange={upd("alpn")} placeholder="h3" />
              </Field>
              <Field label="Fingerprint">
                <Select value={f.fingerprint} onChange={upd("fingerprint")}>
                  {FINGERPRINTS.filter(Boolean).map((fp) => <option key={fp} value={fp}>{fp}</option>)}
                </Select>
              </Field>
            </div>
            <label className="nx-row" style={{ gap: 8, cursor: "pointer" }}>
              <Checkbox checked={f.allowInsecure} onChange={toggle("allowInsecure")} />
              <span>{t("outbounds.allowInsecure")}</span>
            </label>
          </Section>
        )}

        {f.protocol === "tun" && (
          <Section title={t("inbounds.tunSection")}>
            <CalloutInline>{t("inbounds.tunHint")}</CalloutInline>
            <div className="nx-row" style={{ gap: 12, flexWrap: "wrap" }}>
              <Field label={t("inbounds.tunName")}>
                <Input value={f.tunnelAddress} onChange={upd("tunnelAddress")} placeholder="xray0" />
              </Field>
              <Field label="MTU">
                <Input type="number" value={f.wgMtu} onChange={upd("wgMtu")} placeholder="1500" />
              </Field>
            </div>
          </Section>
        )}

        {f.protocol === "shadowsocks" && (
          <Section title="Shadowsocks">
            <div className="nx-row" style={{ gap: 12, flexWrap: "wrap" }}>
              <Field label="Cipher">
                <Select
                  value={f.method}
                  onChange={(e: ChangeEvent<HTMLSelectElement>) => {
                    const method = e.target.value;
                    setF((prev) => ({
                      ...prev,
                      method,
                      ssPassword: isSs2022(method) !== isSs2022(prev.method) ? "" : prev.ssPassword,
                    }));
                  }}
                >
                  <optgroup label="Legacy">
                    {SS_LEGACY_METHODS.map((m) => <option key={m} value={m}>{m}</option>)}
                  </optgroup>
                  <optgroup label="SS-2022">
                    {SS_2022_METHODS.map((m) => <option key={m} value={m}>{m}</option>)}
                  </optgroup>
                </Select>
              </Field>
              <Field label={t("inbounds.network")}>
                <Select value={f.ssNetwork} onChange={upd("ssNetwork")}>
                  {SS_NETWORKS.map((n) => <option key={n} value={n}>{n}</option>)}
                </Select>
              </Field>
            </div>
            {isSs2022(f.method) && (
              <Field label={t("inbounds.ssServerPsk")} hint={t("inbounds.ssServerPskHint")}>
                <Input
                  type="password"
                  value={f.ssPassword}
                  onChange={upd("ssPassword")}
                  placeholder={t("inbounds.ssServerPskPlaceholder")}
                />
              </Field>
            )}
            {isSs2022(f.method) && (
              <CalloutInline>{t("inbounds.ss2022RestartHint")}</CalloutInline>
            )}
          </Section>
        )}

        {(f.protocol === "http" || f.protocol === "socks" || f.protocol === "mixed") && (
          <Section title={f.protocol.toUpperCase()}>
            <CalloutInline>{t("inbounds.proxyAuthHint")}</CalloutInline>
          </Section>
        )}

        {hasStream && (
          <Section title={t("inbounds.sectionTransport")}>
            <div className="nx-row" style={{ gap: 12, flexWrap: "wrap" }}>
              <Field label={t("infra.transport")}>
                <Select value={f.network} onChange={upd("network")}>
                  {NETWORKS.map((n) => <option key={n} value={n}>{n}</option>)}
                </Select>
              </Field>
              {f.protocol === "vless" && (
                <Field label="Flow">
                  <Select value={f.flow} onChange={upd("flow")}>
                    {VLESS_FLOWS.map((fl) => (
                      <option key={fl || "none"} value={fl}>{fl || "(none)"}</option>
                    ))}
                  </Select>
                </Field>
              )}
            </div>
            {(f.network === "ws" || f.network === "grpc" || f.network === "http" || f.network === "h2" || f.network === "httpupgrade" || f.network === "splithttp") && (
              <div className="nx-row" style={{ gap: 12, flexWrap: "wrap" }}>
                <Field label={f.network === "grpc" ? "serviceName" : "path"}>
                  <Input value={f.path} onChange={upd("path")} />
                </Field>
                <Field label="Host">
                  <Input value={f.host} onChange={upd("host")} placeholder="domain.com" />
                </Field>
              </div>
            )}
            {f.network === "grpc" && (
              <label className="nx-row" style={{ gap: 8, cursor: "pointer" }}>
                <Checkbox checked={f.grpcMultiMode} onChange={toggle("grpcMultiMode")} />
                <span>multiMode</span>
              </label>
            )}
            {f.network === "splithttp" && (
              <Field label="mode">
                <Select value={f.xhttpMode} onChange={upd("xhttpMode")}>
                  {["auto", "packet-up", "stream-up", "stream-one"].map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </Select>
              </Field>
            )}
            {f.network === "kcp" && (
              <div className="nx-row" style={{ gap: 12 }}>
                <Field label="seed"><Input value={f.kcpSeed} onChange={upd("kcpSeed")} /></Field>
                <Field label="header">
                  <Select value={f.kcpHeader} onChange={upd("kcpHeader")}>
                    {KCP_HEADERS.map((h) => <option key={h} value={h}>{h}</option>)}
                  </Select>
                </Field>
              </div>
            )}
            {f.network === "quic" && (
              <div className="nx-row" style={{ gap: 12 }}>
                <Field label="key"><Input value={f.path} onChange={upd("path")} /></Field>
                <Field label="header type"><Input value={f.host} onChange={upd("host")} /></Field>
              </div>
            )}
          </Section>
        )}

        {showSecurity && (
          <Section title={t("inbounds.sectionSecurity")}>
            <Field label={t("xray.security")}>
              <Select value={f.security} onChange={upd("security")}>
                {SECURITIES.map((s) => <option key={s} value={s}>{s}</option>)}
              </Select>
            </Field>
            {f.security === "tls" && (
              <div className="nx-row" style={{ gap: 12, flexWrap: "wrap" }}>
                <Field label="SNI"><Input value={f.sni} onChange={upd("sni")} /></Field>
                <Field label="ALPN"><Input value={f.alpn} onChange={upd("alpn")} placeholder="h2,http/1.1" /></Field>
                <Field label="Fingerprint">
                  <Select value={f.fingerprint} onChange={upd("fingerprint")}>
                    {FINGERPRINTS.map((fp) => <option key={fp || "none"} value={fp}>{fp || "(none)"}</option>)}
                  </Select>
                </Field>
                <label className="nx-row" style={{ gap: 8, cursor: "pointer", alignSelf: "end" }}>
                  <Checkbox checked={f.allowInsecure} onChange={toggle("allowInsecure")} />
                  <span>allowInsecure</span>
                </label>
              </div>
            )}
            {f.security === "reality" && (
              <div className="nx-stack" style={{ gap: 10 }}>
                <div className="nx-row" style={{ gap: 8, flexWrap: "wrap" }}>
                  <Button variant="ghost" size="sm" disabled={genKeys} onClick={genReality}>
                    {t("inbounds.getNewCert")}
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => setF((p) => ({ ...p, realityShortIds: randomShortId() }))}>
                    {t("inbounds.newShortId")}
                  </Button>
                </div>
                <Field label="dest"><Input value={f.realityDest} onChange={upd("realityDest")} placeholder="www.google.com:443" /></Field>
                <Field label="SNI / serverNames"><Input value={f.realityServerNames} onChange={upd("realityServerNames")} /></Field>
                <Field label="privateKey"><Input value={f.realityPrivateKey} onChange={upd("realityPrivateKey")} /></Field>
                <Field label={t("inbounds.realityPublicKey")} hint={t("inbounds.realityPublicKeyHint")}>
                  <div className="nx-row" style={{ gap: 8 }}>
                    <Input value={f.realityPublicKey} onChange={upd("realityPublicKey")} placeholder={t("inbounds.realityPublicKeyPlaceholder")} />
                    <CopyButton value={f.realityPublicKey} />
                  </div>
                </Field>
                <Field label="shortIds"><Input value={f.realityShortIds} onChange={upd("realityShortIds")} placeholder="comma separated" /></Field>
                <div className="nx-row" style={{ gap: 12, flexWrap: "wrap" }}>
                  <Field label="Fingerprint">
                    <Select value={f.fingerprint} onChange={upd("fingerprint")}>
                      {FINGERPRINTS.filter(Boolean).map((fp) => <option key={fp} value={fp}>{fp}</option>)}
                    </Select>
                  </Field>
                  <Field label="spiderX"><Input value={f.realitySpiderX} onChange={upd("realitySpiderX")} /></Field>
                  <Field label="xver"><Input value={f.realityXver} onChange={upd("realityXver")} /></Field>
                </div>
              </div>
            )}
          </Section>
        )}

        {supportsFallback(f.protocol) && (
          <Section title={t("inbounds.sectionFallbacks")}>
            <CalloutInline>{t("inbounds.fallbackHint")}</CalloutInline>
            {f.fallbacks.map((fb, idx) => (
              <div
                key={idx}
                className="nx-stack"
                style={{ gap: 10, padding: 12, border: "1px solid var(--nx-border)", borderRadius: 8 }}
              >
                <div className="nx-row" style={{ gap: 12, flexWrap: "wrap" }}>
                  <Field label={t("inbounds.fallbackDest")} hint={t("inbounds.fallbackDestHint")}>
                    <Input value={fb.dest} onChange={updFallback(idx, "dest")} placeholder="8080 / 127.0.0.1:8001" />
                  </Field>
                  <Field label="path">
                    <Input value={fb.path} onChange={updFallback(idx, "path")} placeholder="/ws" />
                  </Field>
                  <Field label="xver">
                    <Input type="number" value={fb.xver} onChange={updFallback(idx, "xver")} />
                  </Field>
                </div>
                <div className="nx-row" style={{ gap: 12, flexWrap: "wrap", alignItems: "end" }}>
                  <Field label="alpn">
                    <Input value={fb.alpn} onChange={updFallback(idx, "alpn")} placeholder="h2 / http/1.1" />
                  </Field>
                  <Field label="name (SNI)">
                    <Input value={fb.name} onChange={updFallback(idx, "name")} placeholder="example.com" />
                  </Field>
                  <Button variant="ghost" size="sm" onClick={() => removeFallback(idx)}>
                    {t("common.remove")}
                  </Button>
                </div>
              </div>
            ))}
            <div>
              <Button variant="ghost" size="sm" onClick={addFallback}>
                {t("inbounds.addFallback")}
              </Button>
            </div>
          </Section>
        )}

        {f.protocol !== "wireguard" && f.protocol !== "amneziawg" && f.protocol !== "hysteria" && f.protocol !== "tun" && f.protocol !== "dokodemo-door" && (
          <Section title={t("inbounds.sectionSniffing")}>
            <label className="nx-row" style={{ gap: 8, cursor: "pointer" }}>
              <Checkbox checked={f.sniffing} onChange={toggle("sniffing")} />
              <span>{t("xray.sniffing")}</span>
            </label>
            {f.sniffing && (
              <Field label={t("inbounds.sniffOverride")}>
                <Input
                  value={f.sniffDestOverride}
                  onChange={upd("sniffDestOverride")}
                  placeholder={SNIFF_OVERRIDES.join(",")}
                />
              </Field>
            )}
          </Section>
        )}
      </div>
    </Modal>
  );
};

const CalloutInline: FC<{ children: React.ReactNode }> = ({ children }) => (
  <p style={{ fontSize: 12, color: "var(--nx-muted)", margin: 0 }}>{children}</p>
);
