import { FC, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { isManageableInbound, inboundDisplayProtocol, inboundTransportLabel } from "../../lib/xrayHelpers";
import { Button, Card, EmptyState, Pill, Toggle, useToast } from "../ui";
import { IcDownload, IcEdit, IcGlobe, IcPlus, IcTrash } from "../icons";
import { TableRowMenu, type TableMenuItem } from "../TableRowMenu";
import { BulkInboundModal } from "../BulkInboundModal";
import { InboundModal } from "@/components/inbound/AddInboundModal";
import { CoreHealthBanner } from "./CoreHealthBanner";
import { SingboxInboundModal, type SingboxInboundEntry } from "./SingboxInboundModal";
import { InboundSubscriptionModal } from "./InboundSubscriptionModal";
import { api } from "../../api/client";
import { useFetch } from "../../lib/useFetch";

export const InboundsSection: FC<{
  config: Record<string, unknown>;
  onChange: (c: Record<string, unknown>) => void;
  onSave: (cfg?: Record<string, unknown>) => void | Promise<void>;
  saving: boolean;
  readOnly?: boolean;
}> = ({ config, onChange, onSave, saving, readOnly = false }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const presets = useFetch<{ presets: Record<string, { label?: string; deploy?: string; protocol?: string }> }>(
    () => api.get("/core/inbounds/presets"),
    [],
  );
  const singboxInbounds = useFetch<{ inbounds: SingboxInboundEntry[] }>(
    () => api.get("/core/inbounds/singbox"),
    [],
  );
  const rawInbounds = (config.inbounds || []) as Record<string, unknown>[];
  const reservedInbounds = rawInbounds.filter((i) => !isManageableInbound(i));
  const manageableInbounds = rawInbounds.filter(isManageableInbound);
  const inbounds = manageableInbounds;
  const sbRows = singboxInbounds.data?.inbounds || [];
  const [modalInbound, setModalInbound] = useState<Record<string, unknown> | null | "new">(null);
  const [singboxModal, setSingboxModal] = useState<{
    presetId: "tuic-inbound" | "anytls-inbound";
    edit?: SingboxInboundEntry | null;
  } | null>(null);
  const [persisting, setPersisting] = useState(false);
  const importInputRef = useRef<HTMLInputElement>(null);
  const [importTargetTag, setImportTargetTag] = useState<string | null>(null);
  const [bulkInboundTag, setBulkInboundTag] = useState<string | null>(null);
  const [subInboundTag, setSubInboundTag] = useState<string | null>(null);

  const singboxPresets = Object.entries(presets.data?.presets || {}).filter(([, p]) => p.deploy === "singbox");

  const reloadSingbox = () => singboxInbounds.reload();

  const withInbounds = (manageable: Record<string, unknown>[]) => ({
    ...config,
    inbounds: [...reservedInbounds, ...manageable],
  });

  const persistConfig = async (merged: Record<string, unknown>) => {
    setPersisting(true);
    try {
      await onSave(merged);
      toast.push(t("xray.savedRestart"), "success");
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.saveFailed"), "error");
      throw e;
    } finally {
      setPersisting(false);
    }
  };

  const applyInbound = async (built: Record<string, unknown>, originalTag?: string) => {
    const inbound: Record<string, unknown> = { enable: true, ...built };
    const next = [...manageableInbounds];
    if (originalTag) {
      const idx = next.findIndex((i) => i.tag === originalTag);
      if (idx >= 0) {
        // Keep enable/disable state across edits unless the payload sets it.
        next[idx] = {
          ...inbound,
          enable: built.enable !== undefined ? built.enable !== false : next[idx].enable !== false,
        };
      } else {
        next.push(inbound);
      }
    } else {
      next.push(inbound);
    }
    const merged = withInbounds(next);
    try {
      await api.post("/core/validate-inbounds", { inbounds: merged.inbounds });
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
      throw e;
    }
    onChange(merged);
    await persistConfig(merged);
  };

  const toggleEnable = async (inbound: Record<string, unknown>) => {
    const tag = String(inbound.tag);
    const currentlyOn = inbound.enable !== false;
    const next = manageableInbounds.map((ib) =>
      String(ib.tag) === tag ? { ...ib, enable: !currentlyOn } : ib,
    );
    const merged = withInbounds(next);
    try {
      await api.post("/core/validate-inbounds", { inbounds: merged.inbounds });
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
      return;
    }
    onChange(merged);
    try {
      await persistConfig(merged);
    } catch {
      /* toast already shown */
    }
  };

  const remove = async (tag: string) => {
    if (!confirm(t("common.confirmDelete"))) return;
    const merged = withInbounds(manageableInbounds.filter((i) => i.tag !== tag));
    onChange(merged);
    await persistConfig(merged);
  };

  const disableSingbox = async (row: SingboxInboundEntry) => {
    if (!confirm(t("common.confirmDelete"))) return;
    try {
      await api.post(`/core/inbounds/singbox/${row.node_id}/${row.protocol}/disable`, {});
      toast.push(t("singboxInbound.disabled"), "success");
      reloadSingbox();
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
    }
  };

  const exportInbound = async (tag: string) => {
    try {
      const res = await api.get<{ inbound: Record<string, unknown> }>(
        `/core/inbounds/${encodeURIComponent(tag)}/export`,
      );
      const blob = new Blob([JSON.stringify(res.inbound, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${tag.replace(/[^\w.-]+/g, "_")}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
      toast.push(t("inbounds.exported"), "success");
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
    }
  };

  const openImportPicker = (tag: string | null) => {
    setImportTargetTag(tag);
    importInputRef.current?.click();
  };

  const parseInboundFile = (raw: string): Record<string, unknown> => {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const inbound = (parsed.inbound ?? parsed) as Record<string, unknown>;
    if (!inbound || typeof inbound !== "object" || !inbound.tag) {
      throw new Error(t("inbounds.importInvalid"));
    }
    return inbound;
  };

  const applyImportedInbound = async (tag: string | null, inbound: Record<string, unknown>) => {
    const merged = tag
      ? await api.post<Record<string, unknown>>(
          `/core/inbounds/${encodeURIComponent(tag)}/import`,
          { inbound },
        )
      : await api.post<Record<string, unknown>>("/core/inbounds/import", { inbound });
    onChange(merged);
    toast.push(t("inbounds.imported"), "success");
  };

  const onImportFileSelected = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    const tag = importTargetTag;
    setImportTargetTag(null);
    if (!file) return;
    try {
      const inbound = parseInboundFile(await file.text());
      await applyImportedInbound(tag, inbound);
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("inbounds.importInvalid"), "error");
    }
  };

  const resetState = () => setModalInbound(null);
  const openAdd = () => setModalInbound("new");
  const openEdit = (inbound: Record<string, unknown>) => setModalInbound(inbound);
  const busy = saving || persisting || readOnly;
  const hasAny = inbounds.length > 0 || sbRows.length > 0;

  return (
    <div className="nx-stack nx-hub-panel">
      <CoreHealthBanner />
      <p className="nx-hub-lede">{t("inbounds.autoPersistHint")}</p>

      <div className="nx-proto-toolbar">
        <div className="nx-proto-toolbar-start">
          {singboxPresets.length > 0 && !readOnly && (
            <>
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => setSingboxModal({ presetId: "tuic-inbound" })}>
                + TUIC
              </Button>
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => setSingboxModal({ presetId: "anytls-inbound" })}>
                + AnyTLS
              </Button>
            </>
          )}
        </div>
        <div className="nx-proto-toolbar-end">
          {!readOnly && (
            <Button size="sm" variant="ghost" onClick={() => openImportPicker(null)} disabled={busy}>
              {t("inbounds.importInbound")}
            </Button>
          )}
          {!readOnly && (
            <Button size="sm" variant="primary" onClick={openAdd} disabled={busy}>
              <IcPlus className="nx-ico" /> {t("infra.addInbound")}
            </Button>
          )}
        </div>
      </div>

      <input
        ref={importInputRef}
        type="file"
        accept="application/json,.json"
        hidden
        onChange={onImportFileSelected}
      />

      <Card pad0>
        {!hasAny ? (
          <EmptyState
            title={t("common.noData")}
            desc={t("inbounds.emptyDesc")}
            action={
              <div className="nx-row" style={{ gap: 8, flexWrap: "wrap", justifyContent: "center" }}>
                <Button variant="primary" onClick={openAdd} disabled={busy}>
                  <IcPlus className="nx-ico" /> {t("infra.addInbound")}
                </Button>
                <Button onClick={() => setSingboxModal({ presetId: "tuic-inbound" })} disabled={busy}>
                  + TUIC
                </Button>
              </div>
            }
          />
        ) : (
          <div className="nx-table-wrap">
            <table className="nx-table">
              <thead>
                <tr>
                  <th>{t("infra.remark")}</th>
                  <th>{t("inbounds.protocol")}</th>
                  <th className="nx-num">{t("infra.port")}</th>
                  <th>{t("infra.transport")}</th>
                  <th>{t("xray.security")}</th>
                  <th>{t("common.status")}</th>
                  <th className="nx-actions" />
                </tr>
              </thead>
              <tbody>
                {sbRows.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <div className="nx-proto-name">
                        <span className="nx-proto-name-main">{row.tag}</span>
                        <span className="nx-proto-name-sub">{row.node_name}</span>
                      </div>
                    </td>
                    <td>
                      <span className="nx-proto-chip">{row.protocol.toUpperCase()}</span>
                      <span className="nx-proto-chip is-muted">sing-box</span>
                    </td>
                    <td className="nx-num nx-mono">{row.port}</td>
                    <td className="nx-proto-meta">{row.transport}</td>
                    <td className="nx-proto-meta">{row.tls_trusted ? "TLS" : "TLS?"}</td>
                    <td><Pill tone={row.node_status === "connected" ? "ok" : "default"} dot>{row.node_status}</Pill></td>
                    <td className="nx-actions">
                      <TableRowMenu
                        items={[
                          {
                            id: "edit",
                            label: t("common.edit"),
                            icon: <IcEdit className="nx-ico" />,
                            disabled: busy,
                            onClick: () => setSingboxModal({ presetId: row.preset_id as "tuic-inbound" | "anytls-inbound", edit: row }),
                          },
                          {
                            id: "del",
                            label: t("common.delete"),
                            icon: <IcTrash className="nx-ico" />,
                            danger: true,
                            disabled: busy,
                            onClick: () => disableSingbox(row),
                          },
                        ]}
                      />
                    </td>
                  </tr>
                ))}
                {inbounds.map((i) => {
                  const ss = (i.streamSettings || {}) as Record<string, unknown>;
                  const displayProto = inboundDisplayProtocol(i);
                  const enabled = i.enable !== false;
                  const sec = String(ss.security || "none");
                  return (
                    <tr key={String(i.tag)} className={enabled ? undefined : "is-muted"}>
                      <td>
                        <span className="nx-proto-name-main">{String(i.tag)}</span>
                      </td>
                      <td><span className="nx-proto-chip">{displayProto}</span></td>
                      <td className="nx-num nx-mono">{String(i.port)}</td>
                      <td className="nx-proto-meta">{inboundTransportLabel(i)}</td>
                      <td>
                        <span className={`nx-proto-meta${sec === "reality" ? " is-warn" : ""}`}>{sec}</span>
                      </td>
                      <td>
                        <Toggle
                          on={enabled}
                          disabled={busy || readOnly}
                          label={enabled ? t("common.disable") : t("common.enable")}
                          onChange={() => toggleEnable(i)}
                        />
                      </td>
                      <td className="nx-actions">
                        <TableRowMenu
                          items={([
                            {
                              id: "export",
                              label: t("inbounds.exportInbound"),
                              icon: <IcDownload className="nx-ico" />,
                              disabled: saving || persisting,
                              onClick: () => exportInbound(String(i.tag)),
                            },
                            ...(readOnly
                              ? []
                              : [
                                  {
                                    id: "import",
                                    label: t("inbounds.importInbound"),
                                    disabled: busy,
                                    onClick: () => openImportPicker(String(i.tag)),
                                  },
                                  {
                                    id: "users",
                                    label: t("bulkInbound.assignShort"),
                                    disabled: busy,
                                    onClick: () => setBulkInboundTag(String(i.tag)),
                                  },
                                  {
                                    id: "sub",
                                    label: t("inboundSub.openModal"),
                                    icon: <IcGlobe className="nx-ico" />,
                                    disabled: busy,
                                    onClick: () => setSubInboundTag(String(i.tag)),
                                  },
                                  {
                                    id: "edit",
                                    label: t("common.edit"),
                                    icon: <IcEdit className="nx-ico" />,
                                    disabled: busy,
                                    onClick: () => openEdit(i),
                                  },
                                  {
                                    id: "del",
                                    label: t("common.delete"),
                                    icon: <IcTrash className="nx-ico" />,
                                    danger: true,
                                    disabled: busy,
                                    onClick: () => remove(String(i.tag)),
                                  },
                                ]),
                          ] as TableMenuItem[])}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <InboundModal
        open={modalInbound !== null}
        initialInbound={modalInbound !== null && modalInbound !== "new" ? modalInbound : null}
        originalTag={
          modalInbound !== null && modalInbound !== "new" ? String(modalInbound.tag) : undefined
        }
        allInbounds={manageableInbounds}
        onClose={resetState}
        onSubmit={async (_config, xrayJson, originalTag) => {
          await applyInbound(xrayJson, originalTag);
          resetState();
        }}
      />

      {singboxModal && (
        <SingboxInboundModal
          presetId={singboxModal.presetId}
          editEntry={singboxModal.edit}
          onClose={() => setSingboxModal(null)}
          onApplied={reloadSingbox}
        />
      )}

      {bulkInboundTag && (
        <BulkInboundModal
          open
          initialInboundTag={bulkInboundTag}
          onClose={() => setBulkInboundTag(null)}
          onDone={() => setBulkInboundTag(null)}
          inboundTags={manageableInbounds.map((i) => String(i.tag))}
        />
      )}

      {subInboundTag && (
        <InboundSubscriptionModal
          inboundTag={subInboundTag}
          onClose={() => setSubInboundTag(null)}
        />
      )}
    </div>
  );
};
