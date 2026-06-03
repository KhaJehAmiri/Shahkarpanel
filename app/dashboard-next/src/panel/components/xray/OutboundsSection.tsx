import { FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { OUTBOUND_PROTOCOLS, socksEndpointFromSettings } from "../../lib/xrayHelpers";
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

  const userOutbounds = outbounds.filter((o) => !SYSTEM_OUT_TAGS.has(String(o.tag)));

  const remove = (idx: number) => {
    const next = [...outbounds];
    next.splice(idx, 1);
    onChange({ ...config, outbounds: next });
  };

  return (
    <div className="nx-stack">
      <Callout tone="info" title={t("xray.outboundsTitle")}>{t("xray.outboundsDesc")}</Callout>
      <div className="nx-row" style={{ justifyContent: "flex-end", gap: 8 }}>
        <Button variant="primary" onClick={() => { setEditIdx(null); setShow(true); }}>
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
                            <Button size="sm" onClick={() => { setEditIdx(idx); setShow(true); }}>
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
  onClose: () => void;
  onApply: (o: Record<string, unknown>[]) => void;
}> = ({ outbounds, editIdx, onClose, onApply }) => {
  const { t } = useTranslation();
  const existing = editIdx != null ? outbounds[editIdx] : null;
  const socksEp = socksEndpointFromSettings(existing?.settings);
  const [tag, setTag] = useState(String(existing?.tag || ""));
  const [protocol, setProtocol] = useState(String(existing?.protocol || "freedom"));
  const [address, setAddress] = useState(socksEp.address);
  const [port, setPort] = useState(socksEp.port);

  const submit = () => {
    const ob: Record<string, unknown> = { tag: tag.trim(), protocol };
    if (protocol === "freedom") ob.settings = {};
    else if (protocol === "blackhole") ob.settings = {};
    else if (protocol === "socks") {
      ob.settings = {
        servers: [{ address: address.trim(), port: parseInt(port, 10) || 1080 }],
      };
    }
    const next = [...outbounds];
    if (editIdx != null) next[editIdx] = ob;
    else next.push(ob);
    onApply(next);
  };

  return (
    <Modal
      open
      title={editIdx != null ? t("common.edit") : t("xray.addOutbound")}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="primary" disabled={!tag} onClick={submit}>{t("common.save")}</Button>
        </>
      }
    >
      <div className="nx-stack">
        <Field label="Tag"><Input value={tag} onChange={(e) => setTag(e.target.value)} autoFocus /></Field>
        <Field label="Protocol">
          <Select value={protocol} onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setProtocol(e.target.value)}>
            {OUTBOUND_PROTOCOLS.map((p) => <option key={p} value={p}>{p}</option>)}
          </Select>
        </Field>
        {protocol === "socks" && (
          <div className="nx-row" style={{ gap: 12 }}>
            <Field label={t("infra.address")}><Input value={address} onChange={(e) => setAddress(e.target.value)} /></Field>
            <Field label={t("infra.port")}><Input type="number" value={port} onChange={(e) => setPort(e.target.value)} /></Field>
          </div>
        )}
      </div>
    </Modal>
  );
};
