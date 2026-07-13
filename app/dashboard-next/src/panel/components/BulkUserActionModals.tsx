import { FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { Button, Field, Input, Modal, useToast } from "./ui";
import type { BulkInboundScope } from "./BulkInboundModal";

export interface BulkUserActionResult {
  applied: number;
  skipped: number;
  failed: number;
  errors: string[];
  duration_ms: number;
}

interface SelectedScopeProps {
  open: boolean;
  onClose: () => void;
  onDone: () => void;
  selectedUsernames: string[];
}

const GB = 1024 * 1024 * 1024;

export const BulkExtendModal: FC<SelectedScopeProps> = ({
  open,
  onClose,
  onDone,
  selectedUsernames,
}) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [days, setDays] = useState("30");
  const [dataGb, setDataGb] = useState("0");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    const n = parseInt(days, 10) || 0;
    const gb = parseFloat(dataGb) || 0;
    if (n < 1 && gb <= 0) {
      toast.push(t("bulkExtend.nothingToApply"), "error");
      return;
    }
    setBusy(true);
    try {
      const r = await api.post<BulkUserActionResult>("/users/bulk/extend", {
        scope: "selected" as BulkInboundScope,
        usernames: selectedUsernames,
        days: n,
        add_data_bytes: Math.round(gb * GB),
      });
      toast.push(
        t("bulkExtend.done", { applied: r.applied, skipped: r.skipped, ms: r.duration_ms }),
        r.failed ? "error" : "success",
      );
      if (r.errors?.length) toast.push(r.errors.slice(0, 3).join("\n"), "error");
      onDone();
      onClose();
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;

  return (
    <Modal
      open={open}
      title={t("bulkExtend.title")}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="primary" disabled={busy} onClick={submit}>
            {busy ? t("common.loading") : t("bulkExtend.apply")}
          </Button>
        </>
      }
    >
      <p className="nx-faint" style={{ fontSize: 13, marginBottom: 14 }}>
        {t("bulkExtend.descData", { n: selectedUsernames.length })}
      </p>
      <Field label={t("bulkExtend.days")}>
        <div className="nx-row" style={{ gap: 8, flexWrap: "wrap" }}>
          <Input
            type="number"
            min={0}
            max={3650}
            value={days}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setDays(e.target.value)}
            style={{ maxWidth: 120 }}
            dir="ltr"
          />
          {[7, 30, 60, 90].map((d) => (
            <Button key={d} size="sm" variant="ghost" onClick={() => setDays(String(d))}>{d}d</Button>
          ))}
        </div>
      </Field>
      <Field label={t("bulkExtend.addData")}>
        <div className="nx-row" style={{ gap: 8, flexWrap: "wrap" }}>
          <Input
            type="number"
            min={0}
            step="0.5"
            value={dataGb}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setDataGb(e.target.value)}
            style={{ maxWidth: 120 }}
            dir="ltr"
          />
          <span className="nx-faint" style={{ alignSelf: "center", fontSize: 13 }}>GB</span>
          {[10, 30, 50, 100].map((g) => (
            <Button key={g} size="sm" variant="ghost" onClick={() => setDataGb(String(g))}>{g}</Button>
          ))}
        </div>
      </Field>
      <p className="nx-faint" style={{ fontSize: 12, marginTop: 4 }}>{t("bulkExtend.addDataHint")}</p>
    </Modal>
  );
};

export const BulkResetUsageModal: FC<SelectedScopeProps> = ({
  open,
  onClose,
  onDone,
  selectedUsernames,
}) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!confirm(t("bulkReset.confirm", { n: selectedUsernames.length }))) return;
    setBusy(true);
    try {
      const r = await api.post<BulkUserActionResult>("/users/bulk/reset-usage", {
        scope: "selected" as BulkInboundScope,
        usernames: selectedUsernames,
      });
      toast.push(
        t("bulkReset.done", { applied: r.applied, skipped: r.skipped, ms: r.duration_ms }),
        r.failed ? "error" : "success",
      );
      if (r.errors?.length) toast.push(r.errors.slice(0, 3).join("\n"), "error");
      onDone();
      onClose();
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;

  return (
    <Modal
      open={open}
      title={t("bulkReset.title")}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="danger" disabled={busy} onClick={submit}>
            {busy ? t("common.loading") : t("bulkReset.apply")}
          </Button>
        </>
      }
    >
      <p className="nx-faint" style={{ fontSize: 13 }}>{t("bulkReset.desc", { n: selectedUsernames.length })}</p>
    </Modal>
  );
};
