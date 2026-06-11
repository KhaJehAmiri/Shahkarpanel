import { FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { isManageableInbound, inboundDisplayProtocol, inboundTransportLabel } from "../../lib/xrayHelpers";
import { Button, Callout, Card, EmptyState, Pill } from "../ui";
import { IcEdit, IcPlus, IcTrash } from "../icons";
import { InboundEditor } from "./InboundEditor";

export const InboundsSection: FC<{
  config: Record<string, unknown>;
  onChange: (c: Record<string, unknown>) => void;
  onSave: () => void;
  saving: boolean;
}> = ({ config, onChange, onSave, saving }) => {
  const { t } = useTranslation();
  const rawInbounds = (config.inbounds || []) as Record<string, unknown>[];
  const reservedInbounds = rawInbounds.filter((i) => !isManageableInbound(i));
  const manageableInbounds = rawInbounds.filter(isManageableInbound);
  const inbounds = manageableInbounds;
  const [show, setShow] = useState(false);
  const [editInbound, setEditInbound] = useState<Record<string, unknown> | null>(null);

  const withInbounds = (manageable: Record<string, unknown>[]) => ({
    ...config,
    inbounds: [...reservedInbounds, ...manageable],
  });

  const remove = (tag: string) => {
    if (!confirm(t("common.confirmDelete"))) return;
    onChange(withInbounds(manageableInbounds.filter((i) => i.tag !== tag)));
  };

  const findIdx = (tag: string) => manageableInbounds.findIndex((i) => i.tag === tag);

  const applyInbound = (built: Record<string, unknown>, originalTag?: string) => {
    const next = [...manageableInbounds];
    if (originalTag) {
      const idx = findIdx(originalTag);
      if (idx >= 0) next[idx] = built;
      else next.push(built);
    } else {
      next.push(built);
    }
    onChange(withInbounds(next));
  };

  return (
    <div className="nx-stack">
      <Callout tone="warn">{t("infra.inboundRestart")}</Callout>
      <Callout tone="info">{t("inbounds.allProtocolsBody")}</Callout>
      <div className="nx-row" style={{ justifyContent: "flex-end", gap: 8, flexWrap: "wrap" }}>
        <Button variant="primary" onClick={() => { setEditInbound(null); setShow(true); }}>
          <IcPlus className="nx-ico" /> {t("infra.addInbound")}
        </Button>
      </div>
      <Card pad0>
        {!inbounds.length ? (
          <EmptyState
            title={t("common.noData")}
            desc={t("inbounds.emptyDesc")}
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
                  <th>{t("infra.remark")}</th>
                  <th>{t("inbounds.protocol")}</th>
                  <th>{t("infra.port")}</th>
                  <th>{t("infra.transport")}</th>
                  <th>{t("xray.security")}</th>
                  <th style={{ textAlign: "end" }}>{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {inbounds.map((i) => {
                  const ss = (i.streamSettings || {}) as Record<string, unknown>;
                  const displayProto = inboundDisplayProtocol(i);
                  return (
                    <tr key={String(i.tag)}>
                      <td style={{ fontWeight: 600 }}>{String(i.tag)}</td>
                      <td><Pill tone="accent">{displayProto}</Pill></td>
                      <td className="nx-mono">{String(i.port)}</td>
                      <td>
                        <Pill tone="default">{inboundTransportLabel(i)}</Pill>
                      </td>
                      <td>
                        <Pill tone={ss.security === "reality" ? "warn" : "default"}>
                          {String(ss.security || "none")}
                        </Pill>
                      </td>
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
        <InboundEditor
          initial={editInbound}
          allInbounds={manageableInbounds}
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
