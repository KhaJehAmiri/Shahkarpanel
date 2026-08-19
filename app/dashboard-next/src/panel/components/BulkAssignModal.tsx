import { FC, useEffect, useMemo, useState, type ChangeEvent } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import type { InboundsByProtocol, NodeItem } from "../api/types";
import { type AssignableNativeProtocols, protocolAssignable } from "../lib/userHelpers";
import { Button, Field, Modal, Select, useToast } from "./ui";

export type BulkInboundScope = "all" | "selected" | "filtered";
export type BulkInboundAction = "add" | "remove";
export type BulkAssignMode = "inbound" | "native";
export type BulkNativeProtocol =
  | "wireguard"
  | "amneziawg"
  | "both"
  | "hysteria2"
  | "tuic"
  | "anytls";
export type BulkNativeAction = "enable" | "disable";

export interface BulkInboundPreview {
  inbound_tag: string;
  action: BulkInboundAction;
  total_users: number;
  would_apply: number;
  already_set: number;
  incompatible: number;
  missing_proxy: number;
}

export interface BulkInboundResult {
  inbound_tag: string;
  action: BulkInboundAction;
  applied: number;
  skipped: number;
  failed: number;
  errors: string[];
  duration_ms: number;
}

export interface BulkNativePreview {
  protocol: string;
  action: string;
  total_users: number;
  would_apply: number;
  already_set: number;
}

export interface BulkNativeResult {
  protocol: string;
  action: string;
  applied: number;
  skipped: number;
  failed: number;
  errors: string[];
  duration_ms: number;
  sync_pending?: boolean;
  sync_ok?: boolean | null;
  sync_nodes?: number;
  singbox_nodes?: number;
  finalmask_reloaded?: boolean;
  sync_ms?: number;
  sync_error?: string | null;
}

const NATIVE_OPTIONS: { id: BulkNativeProtocol; badge: string; labelKey: string }[] = [
  { id: "wireguard", badge: "WG", labelKey: "bulkAssign.protoWireguard" },
  { id: "amneziawg", badge: "AW", labelKey: "bulkAssign.protoAmnezia" },
  { id: "both", badge: "W+", labelKey: "bulkAssign.protoBoth" },
  { id: "hysteria2", badge: "H2", labelKey: "bulkAssign.protoHysteria2" },
  { id: "tuic", badge: "TQ", labelKey: "bulkAssign.protoTuic" },
  { id: "anytls", badge: "AT", labelKey: "bulkAssign.protoAnytls" },
];

interface Props {
  open: boolean;
  onClose: () => void;
  onDone: () => void;
  initialMode?: BulkAssignMode;
  initialInboundTag?: string;
  selectedUsernames?: string[];
  totalUsers?: number;
  inboundTags?: string[];
  inbounds?: InboundsByProtocol;
  nodes?: NodeItem[];
  nativeCaps?: AssignableNativeProtocols | null;
}

export const BulkAssignModal: FC<Props> = ({
  open,
  onClose,
  onDone,
  initialMode = "inbound",
  initialInboundTag = "",
  selectedUsernames = [],
  totalUsers = 0,
  inboundTags = [],
  inbounds,
  nodes,
  nativeCaps,
}) => {
  const { t } = useTranslation();
  const toast = useToast();

  const [mode, setMode] = useState<BulkAssignMode>(initialMode);
  const [inboundTag, setInboundTag] = useState(initialInboundTag);
  const [inboundAction, setInboundAction] = useState<BulkInboundAction>("add");
  const [nativeProto, setNativeProto] = useState<BulkNativeProtocol>("wireguard");
  const [nativeAction, setNativeAction] = useState<BulkNativeAction>("enable");
  const [scope, setScope] = useState<BulkInboundScope>(
    selectedUsernames.length ? "selected" : "all",
  );
  const [statusFilter, setStatusFilter] = useState("");
  const [previewInbound, setPreviewInbound] = useState<BulkInboundPreview | null>(null);
  const [previewNative, setPreviewNative] = useState<BulkNativePreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);

  useEffect(() => {
    if (!open) return;
    setMode(initialMode);
    setInboundTag(initialInboundTag);
    setScope(selectedUsernames.length ? "selected" : "all");
    setPreviewInbound(null);
    setPreviewNative(null);
  }, [open, initialMode, initialInboundTag, selectedUsernames.length]);

  const availableNatives = useMemo(
    () =>
      NATIVE_OPTIONS.filter((opt) => {
        if (opt.id === "both") {
          return (
            protocolAssignable("wireguard", inbounds, nodes, nativeCaps)
            && protocolAssignable("amneziawg", inbounds, nodes, nativeCaps)
          );
        }
        return protocolAssignable(opt.id, inbounds, nodes, nativeCaps);
      }),
    [inbounds, nodes, nativeCaps],
  );

  useEffect(() => {
    if (!availableNatives.length) return;
    if (!availableNatives.some((o) => o.id === nativeProto)) {
      setNativeProto(availableNatives[0].id);
    }
  }, [availableNatives, nativeProto]);

  const scopeBody = useMemo(
    () => ({
      scope,
      usernames: scope === "selected" ? selectedUsernames : [],
      status: scope === "filtered" && statusFilter ? statusFilter : null,
    }),
    [scope, selectedUsernames, statusFilter],
  );

  const clearPreview = () => {
    setPreviewInbound(null);
    setPreviewNative(null);
  };

  const guardScope = (): boolean => {
    if (scope === "selected" && !selectedUsernames.length) {
      toast.push(t("bulkInbound.selectUsers"), "error");
      return false;
    }
    return true;
  };

  const runPreview = async () => {
    if (!guardScope()) return;
    setLoading(true);
    try {
      if (mode === "inbound") {
        if (!inboundTag.trim()) {
          toast.push(t("bulkInbound.inboundRequired"), "error");
          return;
        }
        const p = await api.post<BulkInboundPreview>("/users/bulk/inbounds/preview", {
          ...scopeBody,
          inbound_tag: inboundTag.trim(),
          action: inboundAction,
          ensure_proxy: true,
        });
        setPreviewInbound(p);
        setPreviewNative(null);
      } else {
        const p = await api.post<BulkNativePreview>("/users/bulk/native-protocols/preview", {
          ...scopeBody,
          protocol: nativeProto,
          action: nativeAction,
        });
        setPreviewNative(p);
        setPreviewInbound(null);
      }
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
    } finally {
      setLoading(false);
    }
  };

  const apply = async () => {
    if (!guardScope()) return;
    const would =
      mode === "inbound" ? previewInbound?.would_apply : previewNative?.would_apply;
    if (!would) {
      toast.push(t("bulkAssign.previewFirst"), "error");
      return;
    }
    setApplying(true);
    try {
      if (mode === "inbound") {
        const r = await api.post<BulkInboundResult>("/users/bulk/inbounds", {
          ...scopeBody,
          inbound_tag: inboundTag.trim(),
          action: inboundAction,
          ensure_proxy: true,
        });
        toast.push(
          t("bulkInbound.done", { applied: r.applied, skipped: r.skipped, ms: r.duration_ms }),
          r.failed ? "error" : "success",
        );
        if (r.errors?.length) toast.push(r.errors.slice(0, 3).join("\n"), "error");
      } else {
        const r = await api.post<BulkNativeResult>("/users/bulk/native-protocols", {
          ...scopeBody,
          protocol: nativeProto,
          action: nativeAction,
          wait_sync: true,
        });
        if (r.sync_pending) {
          toast.push(
            t("bulkAssign.donePending", {
              applied: r.applied,
              skipped: r.skipped,
              ms: r.duration_ms,
            }),
            r.failed ? "error" : "success",
          );
        } else if (r.sync_ok === false) {
          toast.push(
            t("bulkAssign.doneSyncFail", {
              applied: r.applied,
              skipped: r.skipped,
              err: r.sync_error || t("common.error"),
              ms: r.duration_ms,
            }),
            "error",
          );
        } else {
          toast.push(
            t("bulkAssign.doneSynced", {
              applied: r.applied,
              skipped: r.skipped,
              nodes: r.sync_nodes ?? 0,
              syncMs: r.sync_ms ?? 0,
              ms: r.duration_ms,
              finalmask: r.finalmask_reloaded
                ? t("bulkAssign.finalmaskFlushed")
                : "",
            }),
            r.failed ? "error" : "success",
          );
        }
        if (r.errors?.length) toast.push(r.errors.slice(0, 3).join("\n"), "error");
      }
      onDone();
      onClose();
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
    } finally {
      setApplying(false);
    }
  };

  const preview = mode === "inbound" ? previewInbound : previewNative;
  const canApply = !!preview && preview.would_apply > 0;

  if (!open) return null;

  return (
    <Modal
      open={open}
      title={t("bulkAssign.title")}
      onClose={onClose}
      wide
      className="sk-bulk-assign-modal"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="ghost" onClick={runPreview} disabled={loading || applying}>
            {loading ? t("common.loading") : t("bulkInbound.preview")}
          </Button>
          <Button variant="primary" onClick={apply} disabled={applying || !canApply}>
            {applying
              ? mode === "native"
                ? t("bulkAssign.applyingSync")
                : t("common.loading")
              : t("bulkInbound.apply")}
          </Button>
        </>
      }
    >
      <p className="sk-bulk-assign-lead">{t("bulkAssign.desc")}</p>
      {applying && mode === "native" ? (
        <p className="sk-bulk-assign-hint">{t("bulkAssign.applyingHint")}</p>
      ) : null}

      <div className="sk-seg sk-seg-stretch sk-bulk-assign-mode" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={mode === "inbound"}
          className={`sk-seg-btn ${mode === "inbound" ? "active" : ""}`}
          onClick={() => { setMode("inbound"); clearPreview(); }}
        >
          {t("bulkAssign.modeInbound")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "native"}
          className={`sk-seg-btn ${mode === "native" ? "active" : ""}`}
          onClick={() => { setMode("native"); clearPreview(); }}
        >
          {t("bulkAssign.modeNative")}
        </button>
      </div>

      {mode === "inbound" ? (
        <div className="sk-bulk-assign-panel">
          <p className="sk-bulk-assign-hint">{t("bulkAssign.inboundHint")}</p>
          <div className="sk-bulk-assign-grid">
            <Field label={t("bulkInbound.inboundTag")}>
              {inboundTags.length ? (
                <Select
                  value={inboundTag}
                  onChange={(e: ChangeEvent<HTMLSelectElement>) => {
                    setInboundTag(e.target.value);
                    clearPreview();
                  }}
                >
                  <option value="">{t("bulkInbound.pickInbound")}</option>
                  {inboundTags.map((tag) => (
                    <option key={tag} value={tag}>{tag}</option>
                  ))}
                </Select>
              ) : (
                <input
                  className="sk-input"
                  value={inboundTag}
                  onChange={(e: ChangeEvent<HTMLInputElement>) => {
                    setInboundTag(e.target.value);
                    clearPreview();
                  }}
                  placeholder="VLESS-Reality"
                  dir="ltr"
                />
              )}
            </Field>
            <Field label={t("bulkInbound.action")}>
              <div className="sk-seg sk-seg-stretch">
                <button
                  type="button"
                  className={`sk-seg-btn ${inboundAction === "add" ? "active" : ""}`}
                  onClick={() => { setInboundAction("add"); clearPreview(); }}
                >
                  {t("bulkAssign.actionAdd")}
                </button>
                <button
                  type="button"
                  className={`sk-seg-btn ${inboundAction === "remove" ? "active" : ""}`}
                  onClick={() => { setInboundAction("remove"); clearPreview(); }}
                >
                  {t("bulkAssign.actionRemove")}
                </button>
              </div>
            </Field>
          </div>
        </div>
      ) : (
        <div className="sk-bulk-assign-panel">
          <p className="sk-bulk-assign-hint">{t("bulkAssign.nativeHint")}</p>
          {nativeProto === "amneziawg" && (
            <p className="sk-bulk-assign-hint">{t("bulkAssign.finalmaskAmneziaNote")}</p>
          )}
          {availableNatives.length === 0 ? (
            <div className="sk-callout sk-bulk-assign-empty">{t("bulkAssign.noNative")}</div>
          ) : (
            <div className="sk-bulk-proto-grid" role="listbox" aria-label={t("bulkAssign.pickProtocol")}>
              {availableNatives.map((opt) => (
                <button
                  key={opt.id}
                  type="button"
                  role="option"
                  aria-selected={nativeProto === opt.id}
                  className={`sk-bulk-proto-card ${nativeProto === opt.id ? "is-active" : ""}`}
                  onClick={() => { setNativeProto(opt.id); clearPreview(); }}
                >
                  <span className="sk-bulk-proto-badge">{opt.badge}</span>
                  <span className="sk-bulk-proto-name">{t(opt.labelKey)}</span>
                </button>
              ))}
            </div>
          )}
          <Field label={t("bulkInbound.action")}>
            <div className="sk-seg sk-seg-stretch">
              <button
                type="button"
                className={`sk-seg-btn ${nativeAction === "enable" ? "active" : ""}`}
                onClick={() => { setNativeAction("enable"); clearPreview(); }}
              >
                {t("bulkAssign.actionEnable")}
              </button>
              <button
                type="button"
                className={`sk-seg-btn ${nativeAction === "disable" ? "active" : ""}`}
                onClick={() => { setNativeAction("disable"); clearPreview(); }}
              >
                {t("bulkAssign.actionDisable")}
              </button>
            </div>
          </Field>
        </div>
      )}

      <div className="sk-bulk-assign-scope">
        <Field label={t("bulkInbound.scope")}>
          <Select
            value={scope}
            onChange={(e: ChangeEvent<HTMLSelectElement>) => {
              setScope(e.target.value as BulkInboundScope);
              clearPreview();
            }}
          >
            {selectedUsernames.length > 0 && (
              <option value="selected">
                {t("bulkInbound.scopeSelected", { n: selectedUsernames.length })}
              </option>
            )}
            <option value="all">{t("bulkInbound.scopeAll", { n: totalUsers || "?" })}</option>
            <option value="filtered">{t("bulkInbound.scopeFiltered")}</option>
          </Select>
        </Field>
        {scope === "filtered" && (
          <Field label={t("common.status")}>
            <Select
              value={statusFilter}
              onChange={(e: ChangeEvent<HTMLSelectElement>) => {
                setStatusFilter(e.target.value);
                clearPreview();
              }}
            >
              <option value="">{t("bulkInbound.anyStatus")}</option>
              {["active", "disabled", "expired", "limited", "on_hold"].map((s) => (
                <option key={s} value={s}>{t(`users.status.${s}`, s)}</option>
              ))}
            </Select>
          </Field>
        )}
      </div>

      {preview && (
        <div className="sk-bulk-assign-preview">
          <div className="sk-bulk-assign-preview-title">{t("bulkInbound.previewResult")}</div>
          <div className="sk-bulk-assign-stats">
            <div className="sk-bulk-stat">
              <span className="sk-bulk-stat-n">{preview.would_apply}</span>
              <span className="sk-bulk-stat-l">{t("bulkAssign.statApply")}</span>
            </div>
            <div className="sk-bulk-stat">
              <span className="sk-bulk-stat-n">{preview.already_set}</span>
              <span className="sk-bulk-stat-l">{t("bulkAssign.statSkip")}</span>
            </div>
            <div className="sk-bulk-stat">
              <span className="sk-bulk-stat-n">{preview.total_users}</span>
              <span className="sk-bulk-stat-l">{t("bulkAssign.statTotal")}</span>
            </div>
            {mode === "inbound" && previewInbound && previewInbound.incompatible > 0 && (
              <div className="sk-bulk-stat is-warn">
                <span className="sk-bulk-stat-n">{previewInbound.incompatible}</span>
                <span className="sk-bulk-stat-l">{t("bulkAssign.statIncompatible")}</span>
              </div>
            )}
            {mode === "inbound" && previewInbound && previewInbound.missing_proxy > 0 && (
              <div className="sk-bulk-stat is-warn">
                <span className="sk-bulk-stat-n">{previewInbound.missing_proxy}</span>
                <span className="sk-bulk-stat-l">{t("bulkAssign.statMissing")}</span>
              </div>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
};

/** Compat wrapper — Inbounds page opens assign modal locked to inbound mode. */
export const BulkInboundModal: FC<Omit<Props, "initialMode">> = (props) => (
  <BulkAssignModal {...props} initialMode="inbound" />
);
