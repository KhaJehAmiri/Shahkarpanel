import { ChangeEvent, FC, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  FINGERPRINTS,
  OUTBOUND_NETWORKS,
  OUTBOUND_PROTOCOLS,
  OUTBOUND_SECURITIES,
  SS_METHODS,
  VLESS_FLOWS,
  buildOutboundFromForm,
  defaultOutboundForm,
  outboundSupportsStream,
  outboundToForm,
  warpOutboundForm,
  type OutboundForm,
} from "../../lib/xrayHelpers";
import { Button, Callout, Card, EmptyState, Field, Input, Modal, Pill, Select } from "../ui";
import { IcEdit, IcPlus, IcTrash } from "../icons";

const SYSTEM_OUT_TAGS = new Set(["DIRECT", "BLOCK", "API"]);

export const OutboundsSection: FC<{
  config: Record<string, unknown>;
  onChange: (c: Record<string, unknown>) => void;
  onSave: () => void;
  saving: boolean;
}> = ({ config, onChange, onSave, saving }) => {
  const { t } = useTranslation();
  const outbounds = (config.outbounds || []) as Record<string, unknown>[];
  const [show, setShow] = useState(false);
  const [editIdx, setEditIdx] = useState<number | null>(null);
  const [preset, setPreset] = useState<OutboundForm | null>(null);

  const openNew = (form: OutboundForm | null) => {
    setEditIdx(null);
    setPreset(form);
    setShow(true);
  };
  const openEdit = (idx: number) => {
    setEditIdx(idx);
    setPreset(null);
    setShow(true);
  };

  const remove = (idx: number) => {
    const next = [...outbounds];
    next.splice(idx, 1);
    onChange({ ...config, outbounds: next });
  };

  return (
    <div className="nx-stack">
      <Callout tone="info" title={t("xray.outboundsTitle")}>{t("xray.outboundsDesc")}</Callout>
      <div className="nx-row" style={{ justifyContent: "flex-end", gap: 8 }}>
        <Button onClick={() => openNew(warpOutboundForm())}>{t("xray.addWarp")}</Button>
        <Button variant="primary" onClick={() => openNew(null)}>
          <IcPlus className="nx-ico" /> {t("xray.addOutbound")}
        </Button>
      </div>
      <Card pad0>
        {!outbounds.length ? (
          <EmptyState title={t("common.noData")} />
        ) : (
          <div className="nx-table-wrap">
            <table className="nx-table">
              <thead>
                <tr>
                  <th>{t("common.name")}</th>
                  <th>Protocol</th>
                  <th style={{ textAlign: "end" }}>{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {outbounds.map((o, idx) => (
                  <tr key={`${o.tag}-${idx}`}>
                    <td style={{ fontWeight: 600 }}>{String(o.tag)}</td>
                    <td><Pill tone="accent">{String(o.protocol)}</Pill></td>
                    <td>
                      <div className="nx-row" style={{ justifyContent: "flex-end", gap: 6 }}>
                        {!SYSTEM_OUT_TAGS.has(String(o.tag)) && (
                          <>
                            <Button size="sm" onClick={() => openEdit(idx)}>
                              <IcEdit className="nx-ico" />
                            </Button>
                            <Button variant="danger" size="sm" onClick={() => remove(idx)}>
                              <IcTrash className="nx-ico" />
                            </Button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <div className="nx-row" style={{ justifyContent: "flex-end" }}>
        <Button variant="primary" disabled={saving} onClick={onSave}>{t("common.save")}</Button>
      </div>
      {show && (
        <OutboundModal
          outbounds={outbounds}
          editIdx={editIdx}
          preset={preset}
          onClose={() => setShow(false)}
          onApply={(next) => { onChange({ ...config, outbounds: next }); setShow(false); }}
        />
      )}
    </div>
  );
};

const OutboundModal: FC<{
  outbounds: Record<string, unknown>[];
  editIdx: number | null;
  preset: OutboundForm | null;
  onClose: () => void;
  onApply: (o: Record<string, unknown>[]) => void;
}> = ({ outbounds, editIdx, preset, onClose, onApply }) => {
  const { t } = useTranslation();
  const existing = editIdx != null ? outbounds[editIdx] : null;
  const [f, setF] = useState<OutboundForm>(
    existing ? outboundToForm(existing) : preset ?? defaultOutboundForm(),
  );

  const upd = (k: keyof OutboundForm) => (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setF((prev) => ({ ...prev, [k]: e.target.value }));

  const submit = () => {
    const ob = buildOutboundFromForm(f);
    const next = [...outbounds];
    if (editIdx != null) next[editIdx] = ob;
    else next.push(ob);
    onApply(next);
  };

  const isProxyServer = f.protocol === "socks" || f.protocol === "http";
  const isVnext = f.protocol === "vless" || f.protocol === "vmess";
  const needsAddress = f.protocol !== "freedom" && f.protocol !== "blackhole" && f.protocol !== "wireguard";
  const hasStream = outboundSupportsStream(f.protocol);

  return (
    <Modal
      open
      wide
      title={editIdx != null ? t("common.edit") : t("xray.addOutbound")}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="primary" disabled={!f.tag.trim()} onClick={submit}>{t("common.save")}</Button>
        </>
      }
    >
      <div className="nx-stack" style={{ maxHeight: "70vh", overflow: "auto", gap: 14 }}>
        <div className="nx-row" style={{ gap: 12, flexWrap: "wrap" }}>
          <Field label="Tag"><Input value={f.tag} onChange={upd("tag")} autoFocus /></Field>
          <Field label="Protocol">
            <Select value={f.protocol} onChange={upd("protocol")}>
              {OUTBOUND_PROTOCOLS.map((p) => <option key={p} value={p}>{p}</option>)}
            </Select>
          </Field>
        </div>

        {needsAddress && (
          <div className="nx-row" style={{ gap: 12, flexWrap: "wrap" }}>
            <Field label={t("infra.address")}><Input value={f.address} onChange={upd("address")} placeholder="example.com" /></Field>
            <Field label={t("infra.port")}><Input type="number" value={f.port} onChange={upd("port")} /></Field>
          </div>
        )}

        {isProxyServer && (
          <div className="nx-row" style={{ gap: 12, flexWrap: "wrap" }}>
            <Field label={t("xray.outUser")}><Input value={f.user} onChange={upd("user")} /></Field>
            <Field label={t("xray.outPass")}><Input value={f.pass} onChange={upd("pass")} /></Field>
          </div>
        )}

        {isVnext && (
          <div className="nx-row" style={{ gap: 12, flexWrap: "wrap" }}>
            <Field label="UUID"><Input value={f.id} onChange={upd("id")} /></Field>
            {f.protocol === "vless" && (
              <Field label="Flow">
                <Select value={f.flow} onChange={upd("flow")}>
                  {VLESS_FLOWS.map((fl) => <option key={fl || "none"} value={fl}>{fl || "(none)"}</option>)}
                </Select>
              </Field>
            )}
          </div>
        )}

        {f.protocol === "trojan" && (
          <Field label={t("xray.outPass")}><Input value={f.pass} onChange={upd("pass")} /></Field>
        )}

        {f.protocol === "shadowsocks" && (
          <div className="nx-row" style={{ gap: 12, flexWrap: "wrap" }}>
            <Field label="Cipher">
              <Select value={f.method} onChange={upd("method")}>
                {SS_METHODS.map((m) => <option key={m} value={m}>{m}</option>)}
              </Select>
            </Field>
            <Field label="Password"><Input value={f.pass} onChange={upd("pass")} /></Field>
          </div>
        )}

        {f.protocol === "wireguard" && (
          <div className="nx-stack" style={{ gap: 12 }}>
            <Callout tone="info" title={t("xray.warpTitle")}>{t("xray.warpDesc")}</Callout>
            <Field label="secretKey"><Input value={f.wgSecretKey} onChange={upd("wgSecretKey")} /></Field>
            <div className="nx-row" style={{ gap: 12, flexWrap: "wrap" }}>
              <Field label={t("xray.wgInterfaceAddress")}><Input value={f.wgAddress} onChange={upd("wgAddress")} /></Field>
              <Field label="reserved"><Input value={f.wgReserved} onChange={upd("wgReserved")} placeholder="0,0,0" /></Field>
            </div>
            <Field label={t("xray.wgPeerPublicKey")}><Input value={f.wgPeerPublicKey} onChange={upd("wgPeerPublicKey")} /></Field>
            <Field label="endpoint"><Input value={f.wgEndpoint} onChange={upd("wgEndpoint")} /></Field>
          </div>
        )}

        {hasStream && (
          <div className="nx-stack" style={{ gap: 12 }}>
            <div className="nx-row" style={{ gap: 12, flexWrap: "wrap" }}>
              <Field label={t("infra.transport")}>
                <Select value={f.network} onChange={upd("network")}>
                  {OUTBOUND_NETWORKS.map((n) => <option key={n} value={n}>{n}</option>)}
                </Select>
              </Field>
              <Field label={t("xray.security")}>
                <Select value={f.security} onChange={upd("security")}>
                  {OUTBOUND_SECURITIES.map((s) => <option key={s} value={s}>{s}</option>)}
                </Select>
              </Field>
            </div>
            {(f.network === "ws" || f.network === "grpc" || f.network === "http" || f.network === "httpupgrade" || f.network === "splithttp") && (
              <div className="nx-row" style={{ gap: 12, flexWrap: "wrap" }}>
                <Field label={f.network === "grpc" ? "serviceName" : "path"}><Input value={f.path} onChange={upd("path")} /></Field>
                <Field label="Host"><Input value={f.hostHeader} onChange={upd("hostHeader")} /></Field>
              </div>
            )}
            {(f.security === "tls" || f.security === "reality") && (
              <div className="nx-row" style={{ gap: 12, flexWrap: "wrap" }}>
                <Field label="SNI"><Input value={f.sni} onChange={upd("sni")} /></Field>
                <Field label="Fingerprint">
                  <Select value={f.fingerprint} onChange={upd("fingerprint")}>
                    {FINGERPRINTS.filter(Boolean).map((fp) => <option key={fp} value={fp}>{fp}</option>)}
                  </Select>
                </Field>
              </div>
            )}
            {f.security === "reality" && (
              <div className="nx-row" style={{ gap: 12, flexWrap: "wrap" }}>
                <Field label="publicKey"><Input value={f.realityPublicKey} onChange={upd("realityPublicKey")} /></Field>
                <Field label="shortId"><Input value={f.realityShortId} onChange={upd("realityShortId")} /></Field>
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
};
