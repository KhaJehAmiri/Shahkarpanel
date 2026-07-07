import { FC, useEffect, useMemo, useState, type ChangeEvent } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { Button, Field, Modal, Select, useToast } from "./ui";

export type BulkInboundScope = "all" | "selected" | "filtered";
export type BulkInboundAction = "add" | "remove";

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

interface Props {
  open: boolean;
  onClose: () => void;
  onDone: () => void;
  /** Pre-fill inbound tag (e.g. from Inbounds page). */
  initialInboundTag?: string;
  /** Usernames when opened from Users multi-select. */
  selectedUsernames?: string[];
  /** Total users in list (for scope hint). */
  totalUsers?: number;
  /** Available inbound tags from live config. */
  inboundTags?: string[];
}

export const BulkInboundModal: FC<Props> = ({
  open,
  onClose,
  onDone,
  initialInboundTag = "",
  selectedUsernames = [],
  totalUsers = 0,
  inboundTags = [],
}) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [inboundTag, setInboundTag] = useState(initialInboundTag);
  const [action, setAction] = useState<BulkInboundAction>("add");
  const [scope, setScope] = useState<BulkInboundScope>(
    selectedUsernames.length ? "selected" : "all",
  );
  const [statusFilter, setStatusFilter] = useState("");
  const [preview, setPreview] = useState<BulkInboundPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);

  useEffect(() => {
    if (open) {
      setInboundTag(initialInboundTag);
      setScope(selectedUsernames.length ? "selected" : "all");
      setPreview(null);
    }
  }, [open, initialInboundTag, selectedUsernames.length]);

  const body = useMemo(
    () => ({
      inbound_tag: inboundTag.trim(),
      action,
      scope,
      usernames: scope === "selected" ? selectedUsernames : [],
      status: scope === "filtered" && statusFilter ? statusFilter : null,
      ensure_proxy: true,
    }),
    [inboundTag, action, scope, selectedUsernames, statusFilter],
  );

  const runPreview = async () => {
    if (!body.inbound_tag) {
      toast.push(t("bulkInbound.inboundRequired"), "error");
      return;
    }
    if (scope === "selected" && !selectedUsernames.length) {
      toast.push(t("bulkInbound.selectUsers"), "error");
      return;
    }
    setLoading(true);
    try {
      const p = await api.post<BulkInboundPreview>("/users/bulk/inbounds/preview", body);
      setPreview(p);
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
    } finally {
      setLoading(false);
    }
  };

  const apply = async () => {
    if (!body.inbound_tag) return;
    setApplying(true);
    try {
      const r = await api.post<BulkInboundResult>("/users/bulk/inbounds", body);
      toast.push(
        t("bulkInbound.done", {
          applied: r.applied,
          skipped: r.skipped,
          ms: r.duration_ms,
        }),
        r.failed ? "error" : "success",
      );
      if (r.errors?.length) {
        toast.push(r.errors.slice(0, 3).join("\n"), "error");
      }
      onDone();
      onClose();
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
    } finally {
      setApplying(false);
    }
  };

  if (!open) return null;

  return (
    <Modal
      open={open}
      title={t("bulkInbound.title")}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="ghost" onClick={runPreview} disabled={loading || applying}>
            {loading ? t("common.loading") : t("bulkInbound.preview")}
          </Button>
          <Button
            variant="primary"
            onClick={apply}
            disabled={applying || !preview?.would_apply}
          >
            {applying ? t("common.loading") : t("bulkInbound.apply")}
          </Button>
        </>
      }
    >
      <p className="nx-faint" style={{ fontSize: 13, marginBottom: 16 }}>{t("bulkInbound.desc")}</p>

      <Field label={t("bulkInbound.inboundTag")}>
        {inboundTags.length ? (
          <Select value={inboundTag} onChange={(e: ChangeEvent<HTMLSelectElement>) => { setInboundTag(e.target.value); setPreview(null); }}>
            <option value="">{t("bulkInbound.pickInbound")}</option>
            {inboundTags.map((tag) => (
              <option key={tag} value={tag}>{tag}</option>
            ))}
          </Select>
        ) : (
          <input
            className="nx-input"
            value={inboundTag}
            onChange={(e: ChangeEvent<HTMLInputElement>) => { setInboundTag(e.target.value); setPreview(null); }}
            placeholder="SS-2022"
            dir="ltr"
          />
        )}
      </Field>

      <Field label={t("bulkInbound.action")}>
        <Select value={action} onChange={(e: ChangeEvent<HTMLSelectElement>) => { setAction(e.target.value as BulkInboundAction); setPreview(null); }}>
          <option value="add">{t("bulkInbound.actionAdd")}</option>
          <option value="remove">{t("bulkInbound.actionRemove")}</option>
        </Select>
      </Field>

      <Field label={t("bulkInbound.scope")}>
        <Select value={scope} onChange={(e: ChangeEvent<HTMLSelectElement>) => { setScope(e.target.value as BulkInboundScope); setPreview(null); }}>
          {selectedUsernames.length > 0 && (
            <option value="selected">{t("bulkInbound.scopeSelected", { n: selectedUsernames.length })}</option>
          )}
          <option value="all">{t("bulkInbound.scopeAll", { n: totalUsers || "?" })}</option>
          <option value="filtered">{t("bulkInbound.scopeFiltered")}</option>
        </Select>
      </Field>

      {scope === "filtered" && (
        <Field label={t("common.status")}>
          <Select value={statusFilter} onChange={(e: ChangeEvent<HTMLSelectElement>) => { setStatusFilter(e.target.value); setPreview(null); }}>
            <option value="">{t("bulkInbound.anyStatus")}</option>
            {["active", "disabled", "expired", "limited", "on_hold"].map((s) => (
              <option key={s} value={s}>{t(`users.status.${s}`, s)}</option>
            ))}
          </Select>
        </Field>
      )}

      {preview && (
        <div className="nx-callout" style={{ marginTop: 16, fontSize: 13 }}>
          <div><b>{t("bulkInbound.previewResult")}</b></div>
          <ul style={{ margin: "8px 0 0", paddingInlineStart: 18 }}>
            <li>{t("bulkInbound.wouldApply", { n: preview.would_apply })}</li>
            <li>{t("bulkInbound.alreadySet", { n: preview.already_set })}</li>
            {preview.incompatible > 0 && <li>{t("bulkInbound.incompatible", { n: preview.incompatible })}</li>}
            {preview.missing_proxy > 0 && <li>{t("bulkInbound.missingProxy", { n: preview.missing_proxy })}</li>}
          </ul>
        </div>
      )}
    </Modal>
  );
};
