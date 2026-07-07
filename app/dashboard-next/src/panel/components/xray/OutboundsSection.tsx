import { FC, useCallback, useState, type ChangeEvent } from "react";
import { useTranslation } from "react-i18next";
import { api, ApiError } from "../../api/client";
import { useFetch } from "../../lib/useFetch";
import { NodeItem } from "../../api/types";
import {
  SYSTEM_OUT_TAGS,
  blackholeOutboundForm,
  cloneOutbound,
  dnsOutboundForm,
  freedomOutboundForm,
  outboundSummary,
  type OutboundForm,
} from "../../lib/outboundHelpers";
import {
  createOutbound,
  removeOutbound,
  reorderOutbounds,
  replaceOutbound,
  upsertOutbound,
} from "../../lib/outboundCrud";
import { Button, Callout, Card, EmptyState, Field, Pill, Select, useToast } from "../ui";
import { IcBolt, IcEdit, IcPlus, IcRefresh, IcShare, IcTrash } from "../icons";
import { OutboundModal } from "./OutboundModal";
import { OutboundPoolDialog } from "./OutboundPoolDialog";
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
  saving: boolean;
}> = ({ config, onChange, saving }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const nodes = useFetch<NodeItem[]>(() => api.get("/nodes"), []);
  const outbounds = (config.outbounds || []) as Record<string, unknown>[];
  const [show, setShow] = useState(false);
  const [editIdx, setEditIdx] = useState<number | null>(null);
  const [preset, setPreset] = useState<OutboundForm | null>(null);
  const [warpOpen, setWarpOpen] = useState(false);
  const [poolOpen, setPoolOpen] = useState(false);
  const [pingMap, setPingMap] = useState<Record<string, PingState>>({});
  const [pingAllRunning, setPingAllRunning] = useState(false);
  const [pingNodeId, setPingNodeId] = useState("");
  const [persisting, setPersisting] = useState(false);

  const pingKey = (o: Record<string, unknown>, idx: number) => String(o.tag || idx);

  const setPing = (key: string, next: PingState) => {
    setPingMap((prev) => ({ ...prev, [key]: next }));
  };

  const commitOutboundChange = async (saved: Record<string, unknown>) => {
    setPersisting(true);
    try {
      onChange(saved);
      toast.push(t("xray.savedRestart"), "success");
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.saveFailed"), "error");
      throw e;
    } finally {
      setPersisting(false);
    }
  };

  const addOutboundApi = async (ob: Record<string, unknown>) => {
    await commitOutboundChange(await createOutbound(ob));
  };

  const updateOutboundApi = async (originalTag: string, ob: Record<string, unknown>) => {
    await commitOutboundChange(await replaceOutbound(originalTag, ob));
  };

  const deleteOutboundApi = async (tag: string) => {
    await commitOutboundChange(await removeOutbound(tag));
  };

  const runPing = useCallback(async (idx: number) => {
    const ob = outbounds[idx];
    if (!ob) return;
    const key = pingKey(ob, idx);
    setPing(key, { loading: true });
    try {
      const body: Record<string, unknown> = {
        outbound: ob,
        allOutbounds: outbounds,
        mode: "auto",
      };
      if (pingNodeId) body.node_id = parseInt(pingNodeId, 10);
      const res = await api.post<OutboundPingResponse>("/core/outbounds/test", body);
      if (res.success) {
        setPing(key, { delay: res.delay ?? 0, mode: res.mode });
      } else {
        setPing(key, { error: res.error || t("outbounds.pingFailed"), mode: res.mode });
      }
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : t("outbounds.pingFailed");
      setPing(key, { error: msg });
    }
  }, [outbounds, pingNodeId, t]);

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

  const remove = async (idx: number) => {
    if (!confirm(t("common.confirmDelete"))) return;
    const tag = String(outbounds[idx]?.tag || "");
    if (!tag) return;
    try {
      await deleteOutboundApi(tag);
    } catch {
      /* toast shown */
    }
  };

  const move = async (idx: number, dir: -1 | 1) => {
    const j = idx + dir;
    if (j < 0 || j >= outbounds.length) return;
    const next = [...outbounds];
    [next[idx], next[j]] = [next[j], next[idx]];
    setPersisting(true);
    try {
      onChange(await reorderOutbounds(next));
      toast.push(t("xray.savedRestart"), "success");
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.saveFailed"), "error");
    } finally {
      setPersisting(false);
    }
  };

  const clone = async (idx: number) => {
    const copy = cloneOutbound(outbounds[idx]);
    let tag = String(copy.tag);
    let n = 2;
    while (outbounds.some((o) => String(o.tag) === tag)) {
      tag = `${String(outbounds[idx].tag)}-${n++}`;
    }
    copy.tag = tag;
    try {
      await addOutboundApi(copy);
    } catch {
      /* toast shown */
    }
  };

  const hasDirect = outbounds.some((o) => String(o.tag) === "DIRECT");
  const hasBlock = outbounds.some((o) => String(o.tag) === "BLOCK");
  const hasDns = outbounds.some((o) => String(o.protocol) === "dns");

  const addWarpOutbound = async (ob: Record<string, unknown>) => {
    const tags = new Set(outbounds.map((o) => String(o.tag)));
    try {
      await commitOutboundChange(await upsertOutbound(ob, tags));
      setWarpOpen(false);
    } catch {
      /* toast shown */
    }
  };

  const addPreset = async (form: OutboundForm) => {
    openNew(form);
  };

  const busy = saving || persisting;
  const connectedNodes = (nodes.data || []).filter((n) => n.status === "connected" && n.core_kind !== "wireguard");

  return (
    <div className="nx-stack">
      <Callout tone="info" title={t("xray.outboundsTitle")}>{t("xray.outboundsDesc")}</Callout>
      <Callout tone="info">{t("outbounds.orderHint")}</Callout>
      <Callout tone="info">{t("inbounds.autoPersistHint")}</Callout>

      <Field label={t("outbounds.pingNode", { defaultValue: "Remote ping node" })} hint={t("outbounds.pingNodeHint", { defaultValue: "Run TCP latency test on a connected node agent (optional)" })}>
        <Select value={pingNodeId} onChange={(e: ChangeEvent<HTMLSelectElement>) => setPingNodeId(e.target.value)} style={{ maxWidth: 320 }}>
          <option value="">{t("outbounds.pingLocal", { defaultValue: "Panel core (local)" })}</option>
          {connectedNodes.map((n) => (
            <option key={n.id} value={n.id}>{n.name} (#{n.id})</option>
          ))}
        </Select>
      </Field>

      <div className="nx-row nx-page-actions" style={{ flexWrap: "wrap", gap: 8 }}>
        {!hasDirect && (
          <Button size="sm" disabled={busy} onClick={() => addPreset(freedomOutboundForm("DIRECT"))}>
            DIRECT
          </Button>
        )}
        {!hasBlock && (
          <Button size="sm" disabled={busy} onClick={() => addPreset(blackholeOutboundForm("BLOCK"))}>
            BLOCK
          </Button>
        )}
        {!hasDns && (
          <Button size="sm" disabled={busy} onClick={() => addPreset(dnsOutboundForm())}>
            DNS
          </Button>
        )}
        <Button size="sm" onClick={() => setWarpOpen(true)} disabled={busy}>{t("xray.addWarp")}</Button>
        <Button size="sm" onClick={() => setPoolOpen(true)} disabled={busy}>
          {t("outboundPool.addPool")}
        </Button>
        <Button size="sm" onClick={pingAll} disabled={!outbounds.length || pingAllRunning}>
          <IcRefresh className="nx-ico" /> {pingAllRunning ? t("outbounds.pingingAll") : t("outbounds.pingAll")}
        </Button>
        <Button variant="primary" onClick={() => openNew(null)} disabled={busy}>
          <IcPlus className="nx-ico" /> {t("xray.addOutbound")}
        </Button>
      </div>

      <Card pad0>
        {!outbounds.length ? (
          <EmptyState
            title={t("common.noData")}
            desc={t("outbounds.emptyDesc")}
            action={
              <Button variant="primary" onClick={() => openNew(null)} disabled={busy}>
                <IcPlus className="nx-ico" /> {t("xray.addOutbound")}
              </Button>
            }
          />
        ) : (
          <div className="nx-table-wrap">
            <table className="nx-table">
              <thead>
                <tr>
                  <th>#</th>
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
                      <td className="nx-faint">{idx + 1}</td>
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
                        <div className="nx-row" style={{ justifyContent: "flex-end", gap: 4 }}>
                          <Button size="sm" title={t("outbounds.moveUp")} disabled={busy || idx === 0} onClick={() => void move(idx, -1)}>↑</Button>
                          <Button size="sm" title={t("outbounds.moveDown")} disabled={busy || idx === outbounds.length - 1} onClick={() => void move(idx, 1)}>↓</Button>
                          <Button size="sm" title={t("outbounds.clone")} disabled={busy} onClick={() => clone(idx)}>
                            <IcShare className="nx-ico" />
                          </Button>
                          {!sys && (
                            <>
                              <Button size="sm" disabled={busy} onClick={() => openEdit(idx)}>
                                <IcEdit className="nx-ico" />
                              </Button>
                              <Button variant="danger" size="sm" disabled={busy} onClick={() => remove(idx)}>
                                <IcTrash className="nx-ico" />
                              </Button>
                            </>
                          )}
                          {sys && (
                            <Button size="sm" disabled={busy} onClick={() => openEdit(idx)}>
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

      {show && (
        <OutboundModal
          outbounds={outbounds}
          editIdx={editIdx}
          preset={preset}
          onClose={() => setShow(false)}
          onApply={async ({ outbound, mode, originalTag }) => {
            try {
              if (mode === "create") {
                await addOutboundApi(outbound);
              } else {
                await updateOutboundApi(originalTag || String(outbound.tag), outbound);
              }
              setShow(false);
            } catch {
              /* toast shown */
            }
          }}
        />
      )}

      {warpOpen && (
        <WarpDialog
          outbounds={outbounds}
          onClose={() => setWarpOpen(false)}
          onAddOutbound={addWarpOutbound}
        />
      )}

      {poolOpen && (
        <OutboundPoolDialog
          onClose={() => setPoolOpen(false)}
          onApplied={async (next) => {
            await commitOutboundChange(next);
          }}
        />
      )}
    </div>
  );
};
