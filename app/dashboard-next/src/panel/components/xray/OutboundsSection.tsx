import { FC, useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, ApiError } from "../../api/client";
import {
  SYSTEM_OUT_TAGS,
  blackholeOutboundForm,
  cloneOutbound,
  dnsOutboundForm,
  freedomOutboundForm,
  outboundSummary,
  type OutboundForm,
} from "../../lib/outboundHelpers";
import { Button, Callout, Card, EmptyState, Pill } from "../ui";
import { IcBolt, IcEdit, IcPlus, IcRefresh, IcShare, IcTrash } from "../icons";
import { OutboundModal } from "./OutboundModal";
import { WarpDialog } from "./WarpDialog";

type PingState = {
  loading?: boolean;
  delay?: number;
  error?: string;
  mode?: string;
};

type OutboundPingResponse = {
  success: boolean;
  delay?: number;
  error?: string;
  mode?: string;
};

export const OutboundsSection: FC<{
  config: Record<string, unknown>;
  onChange: (c: Record<string, unknown>) => void;
  onSave: (next?: Record<string, unknown>) => void;
  saving: boolean;
}> = ({ config, onChange, onSave, saving }) => {
  const { t } = useTranslation();
  const outbounds = (config.outbounds || []) as Record<string, unknown>[];
  const [show, setShow] = useState(false);
  const [editIdx, setEditIdx] = useState<number | null>(null);
  const [preset, setPreset] = useState<OutboundForm | null>(null);
  const [warpOpen, setWarpOpen] = useState(false);
  const [pingMap, setPingMap] = useState<Record<string, PingState>>({});
  const [pingAllRunning, setPingAllRunning] = useState(false);

  const pingKey = (o: Record<string, unknown>, idx: number) => String(o.tag || idx);

  const setPing = (key: string, next: PingState) => {
    setPingMap((prev) => ({ ...prev, [key]: next }));
  };

  const runPing = useCallback(async (idx: number) => {
    const ob = outbounds[idx];
    if (!ob) return;
    const key = pingKey(ob, idx);
    setPing(key, { loading: true });
    try {
      const res = await api.post<OutboundPingResponse>("/core/outbounds/test", {
        outbound: ob,
        allOutbounds: outbounds,
        mode: "auto",
      });
      if (res.success) {
        setPing(key, { delay: res.delay ?? 0, mode: res.mode });
      } else {
        setPing(key, { error: res.error || t("outbounds.pingFailed"), mode: res.mode });
      }
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : t("outbounds.pingFailed");
      setPing(key, { error: msg });
    }
  }, [outbounds, t]);

  const pingAll = async () => {
    if (!outbounds.length || pingAllRunning) return;
    setPingAllRunning(true);
    for (let i = 0; i < outbounds.length; i++) {
      await runPing(i);
    }
    setPingAllRunning(false);
  };

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
    if (!confirm(t("common.confirmDelete"))) return;
    const next = [...outbounds];
    next.splice(idx, 1);
    onChange({ ...config, outbounds: next });
  };

  const clone = (idx: number) => {
    const copy = cloneOutbound(outbounds[idx]);
    let tag = String(copy.tag);
    let n = 2;
    while (outbounds.some((o) => String(o.tag) === tag)) {
      tag = `${String(outbounds[idx].tag)}-${n++}`;
    }
    copy.tag = tag;
    onChange({ ...config, outbounds: [...outbounds, copy] });
  };

  const hasDirect = outbounds.some((o) => String(o.tag) === "DIRECT");
  const hasBlock = outbounds.some((o) => String(o.tag) === "BLOCK");
  const hasDns = outbounds.some((o) => String(o.protocol) === "dns");

  const addWarpOutbound = (ob: Record<string, unknown>) => {
    const tag = String(ob.tag || "warp");
    const idx = outbounds.findIndex((o) => String(o.tag) === tag);
    const next = [...outbounds];
    if (idx >= 0) next[idx] = ob;
    else next.push(ob);
    const nextConfig = { ...config, outbounds: next };
    onChange(nextConfig);
    onSave(nextConfig);
    setWarpOpen(false);
  };

  return (
    <div className="nx-stack">
      <Callout tone="info" title={t("xray.outboundsTitle")}>{t("xray.outboundsDesc")}</Callout>

      <div className="nx-row nx-page-actions" style={{ flexWrap: "wrap", gap: 8 }}>
        {!hasDirect && (
          <Button size="sm" onClick={() => openNew(freedomOutboundForm("DIRECT"))}>
            DIRECT
          </Button>
        )}
        {!hasBlock && (
          <Button size="sm" onClick={() => openNew(blackholeOutboundForm("BLOCK"))}>
            BLOCK
          </Button>
        )}
        {!hasDns && (
          <Button size="sm" onClick={() => openNew(dnsOutboundForm())}>
            DNS
          </Button>
        )}
        <Button size="sm" onClick={() => setWarpOpen(true)}>{t("xray.addWarp")}</Button>
        <Button size="sm" onClick={pingAll} disabled={!outbounds.length || pingAllRunning}>
          <IcRefresh className="nx-ico" /> {pingAllRunning ? t("outbounds.pingingAll") : t("outbounds.pingAll")}
        </Button>
        <Button variant="primary" onClick={() => openNew(null)}>
          <IcPlus className="nx-ico" /> {t("xray.addOutbound")}
        </Button>
      </div>

      <Card pad0>
        {!outbounds.length ? (
          <EmptyState
            title={t("common.noData")}
            desc={t("outbounds.emptyDesc")}
            action={
              <Button variant="primary" onClick={() => openNew(null)}>
                <IcPlus className="nx-ico" /> {t("xray.addOutbound")}
              </Button>
            }
          />
        ) : (
          <div className="nx-table-wrap">
            <table className="nx-table">
              <thead>
                <tr>
                  <th>{t("outbounds.tag")}</th>
                  <th>{t("inbounds.protocol")}</th>
                  <th>{t("infra.address")}</th>
                  <th>{t("infra.transport")}</th>
                  <th>{t("outbounds.ping")}</th>
                  <th>{t("outbounds.extra")}</th>
                  <th style={{ textAlign: "end" }}>{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {outbounds.map((o, idx) => {
                  const sum = outboundSummary(o);
                  const sys = SYSTEM_OUT_TAGS.has(String(o.tag));
                  const pk = pingKey(o, idx);
                  const ping = pingMap[pk];
                  return (
                    <tr key={`${o.tag}-${idx}`}>
                      <td style={{ fontWeight: 600 }}>{String(o.tag)}</td>
                      <td><Pill tone="accent">{String(o.protocol)}</Pill></td>
                      <td className="nx-mono" style={{ fontSize: 12 }}>{sum.address}</td>
                      <td><Pill tone="default">{sum.transport}</Pill></td>
                      <td>
                        <div className="nx-outbound-ping">
                          {ping?.loading ? (
                            <span className="nx-outbound-ping-loading">{t("outbounds.pingRunning")}</span>
                          ) : ping?.delay != null ? (
                            <button
                              type="button"
                              className="nx-outbound-ping-ok"
                              title={ping.mode === "tcp" ? t("outbounds.pingTcpHint") : t("outbounds.pingRetry")}
                              onClick={() => runPing(idx)}
                            >
                              {ping.delay} ms{ping.mode === "tcp" ? " · TCP" : ""}
                            </button>
                          ) : ping?.error ? (
                            <button
                              type="button"
                              className="nx-outbound-ping-err"
                              title={ping.error}
                              onClick={() => runPing(idx)}
                            >
                              {t("outbounds.pingFailedShort")}
                            </button>
                          ) : (
                            <Button size="sm" title={t("outbounds.ping")} onClick={() => runPing(idx)}>
                              <IcBolt className="nx-ico" />
                            </Button>
                          )}
                        </div>
                      </td>
                      <td style={{ fontSize: 12, color: "var(--nx-muted)" }}>{sum.extra}</td>
                      <td>
                        <div className="nx-row" style={{ justifyContent: "flex-end", gap: 6 }}>
                          <Button size="sm" title={t("outbounds.clone")} onClick={() => clone(idx)}>
                            <IcShare className="nx-ico" />
                          </Button>
                          {!sys && (
                            <>
                              <Button size="sm" onClick={() => openEdit(idx)}>
                                <IcEdit className="nx-ico" />
                              </Button>
                              <Button variant="danger" size="sm" onClick={() => remove(idx)}>
                                <IcTrash className="nx-ico" />
                              </Button>
                            </>
                          )}
                          {sys && (
                            <Button size="sm" onClick={() => openEdit(idx)}>
                              <IcEdit className="nx-ico" />
                            </Button>
                          )}
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
        <Button variant="primary" disabled={saving} onClick={() => onSave()}>{t("common.save")}</Button>
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

      {warpOpen && (
        <WarpDialog
          outbounds={outbounds}
          onClose={() => setWarpOpen(false)}
          onAddOutbound={addWarpOutbound}
        />
      )}
    </div>
  );
};
