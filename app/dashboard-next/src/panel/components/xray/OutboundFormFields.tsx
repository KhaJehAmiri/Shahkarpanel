import { ChangeEvent, FC, ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  BLACKHOLE_TYPES,
  DNS_NETWORKS,
  FINGERPRINTS,
  FRAGMENT_PACKETS,
  KCP_HEADERS,
  MUX_XUDP_UDP443,
  OUTBOUND_DOMAIN_STRATEGIES,
  OUTBOUND_PROTOCOLS,
  OUTBOUND_SECURITIES,
  SS_METHODS,
  TRANSMISSION_OPTIONS,
  VLESS_FLOWS,
  VMESS_SECURITIES,
  WIREGUARD_DOMAIN_STRATEGIES,
  outboundSupportsMux,
  outboundSupportsStream,
  type OutboundForm,
} from "../../lib/outboundHelpers";
import { Button, HelpTip, Input, Select, Toggle } from "../ui";
import { IcPlus } from "../icons";

const Req = () => <span className="nx-req" aria-hidden> *</span>;

const FormRow: FC<{ label: ReactNode; help?: string; children: ReactNode }> = ({ label, help, children }) => (
  <div className="nx-form-h-row">
    <div className="nx-form-h-label">
      <span>{label}</span>
      {help && <HelpTip text={help} placement="bottom" />}
    </div>
    <div className="nx-form-h-ctrl">{children}</div>
  </div>
);

const SegSecurity: FC<{ value: string; onChange: (v: string) => void }> = ({ value, onChange }) => (
  <div className="nx-seg nx-seg-stretch">
    {OUTBOUND_SECURITIES.map((s) => (
      <button
        key={s}
        type="button"
        className={`nx-seg-btn ${value === s ? "active" : ""}`}
        onClick={() => onChange(s)}
      >
        {s === "none" ? "None" : s.toUpperCase()}
      </button>
    ))}
  </div>
);

export const OutboundFormFields: FC<{
  f: OutboundForm;
  setF: React.Dispatch<React.SetStateAction<OutboundForm>>;
  chainTags?: string[];
}> = ({ f, setF, chainTags = [] }) => {
  const { t } = useTranslation();

  const upd = (k: keyof OutboundForm) => (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setF((prev) => ({ ...prev, [k]: e.target.value }));

  const toggle = (k: keyof OutboundForm) => (on: boolean) =>
    setF((prev) => ({ ...prev, [k]: on }));

  const setProtocol = (p: string) => {
    setF((prev) => ({
      ...prev,
      protocol: p,
      network: p === "hysteria" ? "hysteria" : "tcp",
      security: p === "trojan" || p === "hysteria" ? "tls" : "none",
      alpn: p === "hysteria" ? "h3" : prev.alpn,
    }));
  };

  const isProxyServer = f.protocol === "socks" || f.protocol === "http";
  const isVnext = f.protocol === "vless" || f.protocol === "vmess";
  const isHysteria = f.protocol === "hysteria";
  const isWgLike = f.protocol === "wireguard" || f.protocol === "amneziawg";
  const needsAddress = !["freedom", "blackhole", "dns"].includes(f.protocol);
  const hasStream = outboundSupportsStream(f.protocol);
  const showMux = outboundSupportsMux(f.protocol, f.flow, f.network);

  return (
    <div className="nx-form-h nx-outbound-form">
      <FormRow label={t("inbounds.protocol")}>
        <Select value={f.protocol} onChange={(e: ChangeEvent<HTMLSelectElement>) => setProtocol(e.target.value)}>
          {OUTBOUND_PROTOCOLS.map((p) => <option key={p} value={p}>{p}</option>)}
        </Select>
      </FormRow>

      <FormRow label={<>{t("outbounds.tag")}<Req /></>}>
        <Input value={f.tag} onChange={upd("tag")} placeholder="unique-tag" autoFocus />
      </FormRow>

      <FormRow label={t("outbounds.sendThrough")} help={t("outbounds.sendThroughHint")}>
        <Input value={f.sendThrough} onChange={upd("sendThrough")} placeholder="local IP" />
      </FormRow>

      {f.protocol === "freedom" && (
        <>
          <FormRow label={t("xray.domainStrategy")}>
            <Select value={f.freedomDomainStrategy} onChange={upd("freedomDomainStrategy")}>
              {OUTBOUND_DOMAIN_STRATEGIES.map((d) => <option key={d} value={d}>{d}</option>)}
            </Select>
          </FormRow>
          <FormRow label={t("outbounds.redirect")}>
            <Input value={f.freedomRedirect} onChange={upd("freedomRedirect")} placeholder="127.0.0.1:1234" />
          </FormRow>
          <FormRow label={t("outbounds.fragment")}>
            <Toggle on={f.freedomFragment} onChange={toggle("freedomFragment")} label={t("outbounds.fragment")} />
          </FormRow>
          {f.freedomFragment && (
            <>
              <FormRow label="packets">
                <Select value={f.fragPackets} onChange={upd("fragPackets")}>
                  {FRAGMENT_PACKETS.map((p) => <option key={p} value={p}>{p}</option>)}
                </Select>
              </FormRow>
              <FormRow label="length"><Input value={f.fragLength} onChange={upd("fragLength")} /></FormRow>
              <FormRow label="interval"><Input value={f.fragInterval} onChange={upd("fragInterval")} /></FormRow>
            </>
          )}
        </>
      )}

      {f.protocol === "blackhole" && (
        <FormRow label={t("outbounds.responseType")}>
          <Select value={f.blackholeType} onChange={upd("blackholeType")}>
            {BLACKHOLE_TYPES.map((b) => <option key={b || "default"} value={b}>{b || "(default)"}</option>)}
          </Select>
        </FormRow>
      )}

      {f.protocol === "dns" && (
        <FormRow label={t("outbounds.dnsNetwork")}>
          <Select value={f.dnsNetwork} onChange={upd("dnsNetwork")}>
            {DNS_NETWORKS.map((n) => <option key={n} value={n}>{n}</option>)}
          </Select>
        </FormRow>
      )}

      {needsAddress && !isWgLike && (
        <>
          <FormRow label={<>{t("infra.address")}<Req /></>}>
            <Input value={f.address} onChange={upd("address")} placeholder="example.com" />
          </FormRow>
          <FormRow label={<>{t("infra.port")}<Req /></>}>
            <Input type="number" value={f.port} onChange={upd("port")} />
          </FormRow>
        </>
      )}

      {isVnext && (
        <>
          <FormRow label="ID">
            <Input value={f.id} onChange={upd("id")} placeholder="UUID" className="nx-mono" />
          </FormRow>
          {f.protocol === "vless" && (
            <>
              <FormRow label="Encryption">
                <Input value={f.encryption} onChange={upd("encryption")} placeholder="none" />
              </FormRow>
              <FormRow label={t("outbounds.reverseTag")}>
                <Input value={f.reverseTag} onChange={upd("reverseTag")} placeholder="optional" />
              </FormRow>
              <FormRow label="Flow">
                <Select value={f.flow} onChange={upd("flow")}>
                  {VLESS_FLOWS.map((fl) => <option key={fl || "none"} value={fl}>{fl || "(none)"}</option>)}
                </Select>
              </FormRow>
            </>
          )}
          {f.protocol === "vmess" && (
            <FormRow label={t("xray.security")}>
              <Select value={f.vmessSecurity} onChange={upd("vmessSecurity")}>
                {VMESS_SECURITIES.map((s) => <option key={s} value={s}>{s}</option>)}
              </Select>
            </FormRow>
          )}
        </>
      )}

      {isProxyServer && (
        <>
          <FormRow label={t("xray.outUser")}><Input value={f.user} onChange={upd("user")} /></FormRow>
          <FormRow label={t("xray.outPass")}><Input value={f.pass} onChange={upd("pass")} /></FormRow>
          {f.protocol === "socks" && (
            <FormRow label={t("outbounds.socksUdp")}>
              <Toggle on={f.socksUdp} onChange={toggle("socksUdp")} label={t("outbounds.socksUdp")} />
            </FormRow>
          )}
        </>
      )}

      {f.protocol === "trojan" && (
        <FormRow label={t("xray.outPass")}><Input value={f.pass} onChange={upd("pass")} /></FormRow>
      )}

      {f.protocol === "shadowsocks" && (
        <>
          <FormRow label="Cipher">
            <Select value={f.method} onChange={upd("method")}>
              {SS_METHODS.map((m) => <option key={m} value={m}>{m}</option>)}
            </Select>
          </FormRow>
          <FormRow label="Password"><Input value={f.pass} onChange={upd("pass")} /></FormRow>
          <FormRow label="UDP over TCP">
            <Toggle on={f.ssUot} onChange={toggle("ssUot")} label="uot" />
          </FormRow>
        </>
      )}

      {f.protocol === "hysteria" && (
        <>
          <FormRow label={<>{t("infra.address")}<Req /></>}>
            <Input value={f.address} onChange={upd("address")} placeholder="example.com" />
          </FormRow>
          <FormRow label={<>{t("infra.port")}<Req /></>}>
            <Input type="number" value={f.port} onChange={upd("port")} />
          </FormRow>
          <FormRow label={t("outbounds.hyAuth")}>
            <Input value={f.pass} onChange={upd("pass")} className="nx-mono" />
          </FormRow>
          <FormRow label={t("outbounds.hyUp")}>
            <Input value={f.hyUp} onChange={upd("hyUp")} placeholder="100 mbps" />
          </FormRow>
          <FormRow label={t("outbounds.hyDown")}>
            <Input value={f.hyDown} onChange={upd("hyDown")} placeholder="100 mbps" />
          </FormRow>
          <FormRow label={t("outbounds.hyUdpIdle")}>
            <Input type="number" value={f.hyUdpIdleTimeout} onChange={upd("hyUdpIdleTimeout")} />
          </FormRow>
          <FormRow label="SNI">
            <Input value={f.sni} onChange={upd("sni")} />
          </FormRow>
          <FormRow label="ALPN">
            <Input value={f.alpn} onChange={upd("alpn")} placeholder="h3" />
          </FormRow>
          <FormRow label="Fingerprint">
            <Select value={f.fingerprint} onChange={upd("fingerprint")}>
              {FINGERPRINTS.filter(Boolean).map((fp) => <option key={fp} value={fp}>{fp}</option>)}
            </Select>
          </FormRow>
          <FormRow label={t("outbounds.allowInsecure")}>
            <Toggle on={f.allowInsecure} onChange={toggle("allowInsecure")} label={t("outbounds.allowInsecure")} />
          </FormRow>
        </>
      )}

      {(f.protocol === "wireguard" || f.protocol === "amneziawg") && (
        <>
          {f.protocol === "amneziawg" && (
            <FormRow label={t("outbounds.amneziaHint")}>
              <span className="nx-faint" style={{ fontSize: 12 }}>{t("outbounds.amneziaJsonHint")}</span>
            </FormRow>
          )}
          <FormRow label="secretKey"><Input value={f.wgSecretKey} onChange={upd("wgSecretKey")} className="nx-mono" /></FormRow>
          <FormRow label={t("xray.wgInterfaceAddress")}><Input value={f.wgAddress} onChange={upd("wgAddress")} /></FormRow>
          <FormRow label="reserved"><Input value={f.wgReserved} onChange={upd("wgReserved")} placeholder="0,0,0" /></FormRow>
          <FormRow label={t("xray.wgPeerPublicKey")}><Input value={f.wgPeerPublicKey} onChange={upd("wgPeerPublicKey")} /></FormRow>
          <FormRow label="endpoint"><Input value={f.wgEndpoint} onChange={upd("wgEndpoint")} /></FormRow>
          <FormRow label="mtu"><Input value={f.wgMtu} onChange={upd("wgMtu")} /></FormRow>
          <FormRow label={t("xray.domainStrategy")}>
            <Select value={f.wgDomainStrategy} onChange={upd("wgDomainStrategy")}>
              {WIREGUARD_DOMAIN_STRATEGIES.map((d) => <option key={d || "default"} value={d}>{d || "(default)"}</option>)}
            </Select>
          </FormRow>
        </>
      )}

      {hasStream && !isHysteria && (
        <>
          <FormRow label={t("outbounds.transmission")}>
            <Select
              value={f.network}
              onChange={(e: ChangeEvent<HTMLSelectElement>) =>
                setF((p) => ({ ...p, network: e.target.value, tcpHttpCamo: e.target.value !== "tcp" ? false : p.tcpHttpCamo }))
              }
            >
              {TRANSMISSION_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </Select>
          </FormRow>

          <FormRow label={t("outbounds.httpObfuscation")}>
            <Toggle
              on={f.tcpHttpCamo}
              onChange={(on) => setF((p) => ({ ...p, tcpHttpCamo: on, network: "tcp" }))}
              label={t("outbounds.httpObfuscation")}
              disabled={f.network !== "tcp"}
            />
          </FormRow>

          <FormRow label={t("xray.security")}>
            <SegSecurity value={f.security} onChange={(v) => setF((p) => ({ ...p, security: v }))} />
          </FormRow>

          <FormRow label={t("outbounds.sockopts")}>
            <Toggle
              on={f.sockoptsEnabled}
              onChange={toggle("sockoptsEnabled")}
              label={t("outbounds.sockopts")}
            />
          </FormRow>

          {f.sockoptsEnabled && (
            <FormRow label={t("outbounds.dialerProxy")} help={t("outbounds.dialerProxyHint")}>
              <Select value={f.dialerProxy} onChange={upd("dialerProxy")}>
                <option value="">(optional)</option>
                {chainTags.filter((tg) => tg && tg !== f.tag).map((tg) => (
                  <option key={tg} value={tg}>{tg}</option>
                ))}
              </Select>
            </FormRow>
          )}

          {(f.network === "ws" || f.network === "grpc" || f.network === "http" || f.network === "httpupgrade" || f.network === "splithttp" || f.network === "xhttp" || f.tcpHttpCamo) && (
            <>
              <FormRow label={f.network === "grpc" ? "serviceName" : "path"}>
                <Input value={f.path} onChange={upd("path")} />
              </FormRow>
              <FormRow label="Host"><Input value={f.hostHeader} onChange={upd("hostHeader")} /></FormRow>
              {f.network === "grpc" && (
                <FormRow label="multiMode">
                  <Toggle on={f.grpcMultiMode} onChange={toggle("grpcMultiMode")} label="multiMode" />
                </FormRow>
              )}
              {f.network === "xhttp" && (
                <FormRow label="mode"><Input value={f.xhttpMode} onChange={upd("xhttpMode")} placeholder="auto" /></FormRow>
              )}
            </>
          )}

          {(f.network === "kcp" || f.network === "quic") && (
            <>
              {f.network === "kcp" && (
                <FormRow label="seed"><Input value={f.kcpSeed} onChange={upd("kcpSeed")} /></FormRow>
              )}
              <FormRow label="header type">
                <Select value={f.kcpHeader} onChange={upd("kcpHeader")}>
                  {KCP_HEADERS.map((h) => <option key={h} value={h}>{h}</option>)}
                </Select>
              </FormRow>
            </>
          )}

          {(f.security === "tls" || f.security === "reality") && (
            <>
              <FormRow label="SNI"><Input value={f.sni} onChange={upd("sni")} /></FormRow>
              <FormRow label="ALPN"><Input value={f.alpn} onChange={upd("alpn")} placeholder="h2,http/1.1" /></FormRow>
              <FormRow label="Fingerprint">
                <Select value={f.fingerprint} onChange={upd("fingerprint")}>
                  {FINGERPRINTS.filter(Boolean).map((fp) => <option key={fp} value={fp}>{fp}</option>)}
                </Select>
              </FormRow>
              {f.security === "tls" && (
                <FormRow label="allowInsecure">
                  <Toggle on={f.allowInsecure} onChange={toggle("allowInsecure")} label="allowInsecure" />
                </FormRow>
              )}
            </>
          )}

          {f.security === "reality" && (
            <>
              <FormRow label="publicKey"><Input value={f.realityPublicKey} onChange={upd("realityPublicKey")} /></FormRow>
              <FormRow label="shortId"><Input value={f.realityShortId} onChange={upd("realityShortId")} /></FormRow>
              <FormRow label="spiderX"><Input value={f.realitySpiderX} onChange={upd("realitySpiderX")} /></FormRow>
            </>
          )}

          <FormRow label={t("outbounds.tcpMasks")} help={t("outbounds.tcpMasksHint")}>
            <Button size="sm" variant="primary" type="button" disabled title={t("outbounds.tcpMasksHint")}>
              <IcPlus className="nx-ico" />
            </Button>
          </FormRow>

          {showMux && (
            <>
              <FormRow label="Mux">
                <Toggle on={f.muxEnabled} onChange={toggle("muxEnabled")} label="Mux" />
              </FormRow>
              {f.muxEnabled && (
                <>
                  <FormRow label="concurrency"><Input value={f.muxConcurrency} onChange={upd("muxConcurrency")} /></FormRow>
                  <FormRow label="xudpConcurrency"><Input value={f.muxXudpConcurrency} onChange={upd("muxXudpConcurrency")} /></FormRow>
                  <FormRow label="xudpProxyUDP443">
                    <Select value={f.muxXudpProxyUDP443} onChange={upd("muxXudpProxyUDP443")}>
                      {MUX_XUDP_UDP443.map((v) => <option key={v} value={v}>{v}</option>)}
                    </Select>
                  </FormRow>
                </>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
};
