import { FC, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useApp } from "../context/AppContext";
import { Button, Callout, Modal, useToast } from "./ui";
import { IcDownload } from "./icons";

/** Simple 3x-ui-style Backup / Restore dialog for the Overview page. */
export const BackupRestoreModal: FC<{ open: boolean; onClose: () => void }> = ({ open, onClose }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const { hasPermission } = useApp();
  const canWrite = hasPermission("backup:write");
  const [busy, setBusy] = useState<"backup" | "restore" | null>(null);
  const uploadRef = useRef<HTMLInputElement>(null);

  if (!open) return null;

  const downloadBackup = async () => {
    setBusy("backup");
    try {
      await api.download("/backup/download", "shahkar-backup.tar.gz");
      toast.push(t("system.backupDownloaded"), "success");
    } catch (e: any) {
      toast.push(e?.message || t("common.error"), "error");
    } finally {
      setBusy(null);
    }
  };

  const onRestoreFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (!confirm(t("system.uploadRestoreConfirm"))) return;
    setBusy("restore");
    try {
      const form = new FormData();
      form.append("file", file);
      await api.upload("/backup/restore", form);
      toast.push(t("system.restoreDoneRestarting"), "success");
      onClose();
    } catch (err: any) {
      toast.push(err?.message || t("common.error"), "error");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal
      open
      title={t("overview.backupRestore")}
      onClose={onClose}
      footer={<Button variant="ghost" disabled={!!busy} onClick={onClose}>{t("common.close")}</Button>}
    >
      <p className="sk-muted" style={{ marginTop: 0, marginBottom: 16, fontSize: 13, lineHeight: 1.5 }}>
        {t("overview.backupRestoreHint")}
      </p>

      <div className="sk-stack" style={{ gap: 12 }}>
        <button
          type="button"
          className="sk-quick-card accent"
          disabled={!!busy}
          onClick={downloadBackup}
          style={{ width: "100%", textAlign: "start", cursor: busy ? "wait" : "pointer" }}
        >
          <IcDownload className="sk-ico" />
          <span style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-start" }}>
            <strong>{busy === "backup" ? t("common.loading") : t("system.downloadBackup")}</strong>
            <span className="sk-muted" style={{ fontSize: 12, fontWeight: 400 }}>
              {t("overview.backupCardHint")}
            </span>
          </span>
        </button>

        {canWrite ? (
          <>
            <input
              ref={uploadRef}
              type="file"
              accept=".dump,.db,.sql,.tar.gz,.tgz,application/gzip,application/octet-stream"
              style={{ display: "none" }}
              onChange={onRestoreFile}
            />
            <button
              type="button"
              className="sk-quick-card"
              disabled={!!busy}
              onClick={() => uploadRef.current?.click()}
              style={{
                width: "100%",
                textAlign: "start",
                cursor: busy ? "wait" : "pointer",
                borderColor: "color-mix(in srgb, var(--sk-danger) 35%, transparent)",
              }}
            >
              <IcDownload className="sk-ico" style={{ transform: "rotate(180deg)", color: "var(--sk-danger)" }} />
              <span style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-start" }}>
                <strong style={{ color: "var(--sk-danger)" }}>
                  {busy === "restore" ? t("common.loading") : t("system.restoreBackup")}
                </strong>
                <span className="sk-muted" style={{ fontSize: 12, fontWeight: 400 }}>
                  {t("overview.restoreCardHint")}
                </span>
              </span>
            </button>
          </>
        ) : (
          <Callout tone="info">{t("overview.backupReadOnly")}</Callout>
        )}
      </div>
    </Modal>
  );
};
