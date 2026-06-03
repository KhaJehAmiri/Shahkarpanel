import { FC, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  NETWORKS, USER_PROTOCOLS, SECURITIES, SS_METHODS, VLESS_FLOWS,
  buildInboundFromForm, defaultInboundForm, inboundToForm, isUserInbound,
  type InboundForm,
} from "../../lib/xrayHelpers";
import { Button, Callout, Card, Checkbox, EmptyState, Field, Input, Modal, Pill, Select, useToast } from "../ui";
import { IcEdit, IcPlus, IcRefresh, IcTrash } from "../icons";

export const InboundsSection: FC<{
  config: Record<string, unknown>;
  onChange: (c: Record<string, unknown>) => void;
  onSave: () => void;
  saving: boolean;
}> = ({ config, onChange, onSave, saving }) => {
  const { t } = useTranslation();
  const inbounds = ((config.inbounds || []) as Record<string, unknown>[]).filter(isUserInbound);
  const allInbounds = (config.inbounds || []) as Record<string, unknown>[];
  const [show, setShow] = useState(false);
  const [editInbound, setEditInbound] = useState<Record<string, unknown> | null>(null);

  const remove = (tag: string) => {
    if (!confirm(t("common.confirmDelete"))) return;
    onChange({
      ...config,
      inbounds: allInbounds.filter((i) => i.tag !== tag),
    });
  };

  const findIdx = (tag: string) => allInbounds.findIndex((i) => i.tag === tag);

  const applyInbound = (built: Record<string, unknown>, originalTag?: string) => {
    const next = [...allInbounds];
    if (originalTag) {
      const idx = findIdx(originalTag);
      if (idx >= 0) next[idx] = built;
      else next.push(built);
    } else {
      next.push(built);
    }
    onChange({ ...config, inbounds: next });
  };

  return (
    <div className="nx-stack">
      <Callout tone="info" title={t("xray.inboundsTitle")}>{t("xray.inboundsDesc")}</Callout>
      <Callout tone="warn">{t("infra.inboundRestart")}</Callout>
      <div className="nx-row" style={{ justifyContent: "flex-end", gap: 8 }}>
        <Button variant="primary" onClick={() => { setEditInbound(null); setShow(true); }}>
          <IcPlus className="nx-ico" /> {t("infra.addInbound")}
        </Button>
      </div>
      <Card pad0>
        {!inbounds.length ? (
          <EmptyState
            title={t("common.noData")}
            action={
              <Button variant="primary" onClick={() => { setEditInbound(null); setShow(true); }}>
                <IcPlus className="nx-ico" /> {t("infra.addInbound")}
              </Button>
            }
          />
        ) : (
          <div className="nx-table-wrap">
            <table className="nx-table">
              <thead>
                <tr>
                  <th>{t("common.name")}</th>
                  <th>Protocol</th>
                  <th>{t("infra.port")}</th>
                  <th>{t("infra.transport")}</th>
                  <th>{t("xray.security")}</th>
                  <th style={{ textAlign: "end" }}>{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {inbounds.map((i) => {
                  const ss = (i.streamSettings || {}) as Record<string, unknown>;
                  return (
                    <tr key={String(i.tag)}>
                      <td style={{ fontWeight: 600 }}>{String(i.tag)}</td>
                      <td><Pill tone="accent">{String(i.protocol)}</Pill></td>
                      <td className="nx-mono">{String(i.port)}</td>
                      <td>{String(ss.network || "tcp")}</td>
                      <td><Pill tone={ss.security === "reality" ? "warn" : "default"}>{String(ss.security || "none")}</Pill></td>
                      <td>
                        <div className="nx-row" style={{ justifyContent: "flex-end", gap: 6 }}>
                          <Button size="sm" onClick={() => { setEditInbound(i); setShow(true); }}>
                            <IcEdit className="nx-ico" />
                          </Button>
                          <Button variant="danger" size="sm" onClick={() => remove(String(i.tag))}>
                            <IcTrash className="nx-ico" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <div className="nx-row" style={{ justifyContent: "flex-end" }}>
        <Button variant="primary" disabled={saving} onClick={onSave}>{t("common.save")}</Button>
      </div>
      {show && (
        <InboundModal
          initial={editInbound}
          allInbounds={allInbounds}
          onClose={() => setShow(false)}
          onApply={(built, originalTag) => {
            applyInbound(built, originalTag);
            setShow(false);
          }}
        />
      )}
    </div>
  );
};

const InboundModal: FC<{
  initial: Record<string, unknown> | null;
  allInbounds: Record<string, unknown>[];
  onClose: () => void;
  onApply: (built: Record<string, unknown>, originalTag?: string) => void;
}> = ({ initial, allInbounds, onClose, onApply }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [f, setF] = useState<InboundForm>(initial ? inboundToForm(initial) : defaultInboundForm());
  const originalTag = initial ? String(initial.tag) : undefined;
  const upd = (k: keyof InboundForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setF({ ...f, [k]: e.target.value });
  const setBool = (k: "sniffing") => () => setF({ ...f, [k]: !f[k] });

  const submit = () => {
    const clash = allInbounds.some(
      (i) =>
        i.tag !== originalTag &&
        (String(i.tag) === f.tag.trim() || String(i.port) === f.port),
    );
    if (clash) {
      toast.push(t("xray.tagPortConflict"), "error");
      return;
    }
    onApply(buildInboundFromForm(f), originalTag);
  };

  return (
    <Modal
      open
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
      <div className="nx-stack" style={{ maxHeight: "70vh", overflow: "auto" }}>
        <div className="nx-row" style={{ gap: 12, flexWrap: "wrap" }}>
          <Field label={`${t("common.name")} (tag)`}>
            <Input value={f.tag} onChange={upd("tag")} autoFocus />
          </Field>
          <Field label={t("xray.listen")}>
            <Input value={f.listen} onChange={upd("listen")} placeholder="0.0.0.0" />
          </Field>
          <Field label={t("infra.port")}>
            <Input type="number" value={f.port} onChange={upd("port")} />
          </Field>
        </div>
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label="Protocol">
            <Select value={f.protocol} onChange={upd("protocol")}>
              {USER_PROTOCOLS.map((p) => <option key={p} value={p}>{p}</option>)}
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
          {f.protocol === "shadowsocks" && (
            <Field label="method">
              <Select value={f.method} onChange={upd("method")}>
                {SS_METHODS.map((m) => <option key={m} value={m}>{m}</option>)}
              </Select>
            </Field>
          )}
        </div>
        {f.protocol !== "shadowsocks" && (
          <>
            <div className="nx-row" style={{ gap: 12 }}>
              <Field label={t("infra.transport")}>
                <Select value={f.network} onChange={upd("network")}>
                  {NETWORKS.map((n) => <option key={n} value={n}>{n}</option>)}
                </Select>
              </Field>
              {(f.network === "ws" || f.network === "grpc") && (
                <Field label={f.network === "ws" ? "path" : "serviceName"}>
                  <Input value={f.path} onChange={upd("path")} />
                </Field>
              )}
            </div>
            <Field label={t("xray.security")}>
              <Select value={f.security} onChange={upd("security")}>
                {SECURITIES.map((s) => <option key={s} value={s}>{s}</option>)}
              </Select>
            </Field>
            {f.security === "tls" && (
              <div className="nx-row" style={{ gap: 12, flexWrap: "wrap" }}>
                <Field label="SNI"><Input value={f.sni} onChange={upd("sni")} /></Field>
                <Field label="ALPN"><Input value={f.alpn} onChange={upd("alpn")} placeholder="h2,http/1.1" /></Field>
                <Field label="Fingerprint"><Input value={f.fingerprint} onChange={upd("fingerprint")} placeholder="chrome" /></Field>
              </div>
            )}
            {f.security === "reality" && (
              <div className="nx-stack" style={{ gap: 10 }}>
                <Field label="dest"><Input value={f.realityDest} onChange={upd("realityDest")} placeholder="www.google.com:443" /></Field>
                <Field label="serverNames"><Input value={f.realityServerNames} onChange={upd("realityServerNames")} placeholder="www.google.com" /></Field>
                <Field label="privateKey"><Input value={f.realityPrivateKey} onChange={upd("realityPrivateKey")} /></Field>
                <Field label="shortIds"><Input value={f.realityShortIds} onChange={upd("realityShortIds")} placeholder=", separated" /></Field>
                <Field label="Fingerprint"><Input value={f.fingerprint} onChange={upd("fingerprint")} placeholder="chrome" /></Field>
              </div>
            )}
            <label className="nx-row" style={{ gap: 8, cursor: "pointer" }}>
              <Checkbox checked={f.sniffing} onChange={setBool("sniffing")} />
              <span>{t("xray.sniffing")}</span>
            </label>
          </>
        )}
      </div>
    </Modal>
  );
};
