import { FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { ImportPreviewResponse } from "../api/types";
import { formatBytes } from "../lib/format";
import {
  Button, Callout, Field, Modal, Pill, Select, useToast,
} from "./ui";

const ACCEPT =
  ".json,.csv,.txt,.dump,.db,.sql,.sqlite,.sqlite3,application/octet-stream";

export const UserImportWizard: FC<{
  onClose: () => void;
  onDone: () => void;
  /** Emphasize dump restore (reseller migration tab). */
  dumpFocus?: boolean;
}> = ({ onClose, onDone, dumpFocus }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreviewResponse | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [skipExisting, setSkipExisting] = useState(true);
  const [busy, setBusy] = useState(false);

  const rows = preview?.rows || [];
  const panelTags = preview?.panel_inbound_tags || [];
  const unmapped = Array.from(new Set(rows.flatMap((r) => r.unmapped_inbounds || [])));
  const counts = preview?.counts;

  const runPreview = async () => {
    if (!file) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await api.upload<ImportPreviewResponse>("/users/import/preview", fd);
      setPreview(res);
      setMapping({});
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!file) return;
    if (!counts?.new) {
      toast.push(t("users.importNothingNew"), "error");
      return;
    }
    if (!confirm(t("users.importApplyConfirm", { n: counts.new }))) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("skip_existing", String(skipExisting));
      fd.append("inbound_mapping", JSON.stringify(mapping));
      const res = await api.upload<{ created: number; skipped: number; errors: string[]; source?: string }>(
        "/users/import/apply-file",
        fd,
      );
      toast.push(t("users.importDone", { created: res.created, skipped: res.skipped }), "success");
      if (res.errors.length) toast.push(res.errors.slice(0, 5).join("; "), "error");
      onDone();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      title={dumpFocus ? t("resellers.migrationDumpTitle") : t("users.import")}
      onClose={onClose}
      wide
      footer={(
        <>
          <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="ghost" disabled={busy || !file} onClick={runPreview}>{t("users.importPreview")}</Button>
          <Button variant="primary" disabled={busy || !file || !counts?.new} onClick={apply}>{t("users.importApply")}</Button>
        </>
      )}
    >
      <Callout tone="info" title={dumpFocus ? t("resellers.migrationDumpHintTitle") : t("users.importWhere")}>
        <div className="sk-stack" style={{ gap: 6, fontSize: 13 }}>
          {dumpFocus && <div>{t("users.importFmt3xuiDump")}</div>}
          <div>{t("users.importFmtMarzban")}</div>
          <div>{t("users.importFmt3xui")}</div>
          {!dumpFocus && <div>{t("users.importFmt3xuiDump")}</div>}
          <div>{t("users.importFmtCsv")}</div>
          <div>{t("users.importFmtLinks")}</div>
        </div>
      </Callout>
      <div style={{ marginTop: 12 }}>
        <Field label={dumpFocus ? t("resellers.migrationDumpFile") : t("users.importFile")}>
          <input
            type="file"
            accept={ACCEPT}
            onChange={(e) => {
              setFile(e.target.files?.[0] || null);
              setPreview(null);
              setMapping({});
            }}
          />
        </Field>
      </div>
      <label className="sk-row" style={{ gap: 8, marginTop: 8, fontSize: 13 }}>
        <input type="checkbox" checked={skipExisting} onChange={(e) => setSkipExisting(e.target.checked)} />
        {t("users.importSkipExisting")}
      </label>
      {preview && (
        <div className="sk-row" style={{ gap: 10, marginTop: 10, flexWrap: "wrap", fontSize: 12 }}>
          <Pill tone="accent">{t("users.importSource")}: {preview.source || "—"}</Pill>
          <Pill>{t("users.importTotal")}: {counts?.total ?? preview.total}</Pill>
          <Pill tone="ok">{t("users.importNew")}: {counts?.new ?? 0}</Pill>
          <Pill>{t("users.importExists")}: {counts?.exists ?? 0}</Pill>
          {(counts?.invalid ?? 0) > 0 && <Pill tone="warn">{t("users.importInvalid")}: {counts?.invalid}</Pill>}
          {preview.truncated && <span className="sk-faint">{t("users.importTruncated")}</span>}
        </div>
      )}
      {unmapped.length > 0 && (
        <Callout tone="warn" title={t("users.importMapTitle")}>
          <div className="sk-stack" style={{ gap: 8, marginTop: 8 }}>
            {unmapped.map((tag) => (
              <div key={tag} className="sk-row" style={{ gap: 8, flexWrap: "wrap" }}>
                <span className="sk-code">{tag}</span>
                <span>→</span>
                <Select
                  value={mapping[tag] || ""}
                  onChange={(e: any) => setMapping({ ...mapping, [tag]: e.target.value })}
                  style={{ minWidth: 160 }}
                >
                  <option value="">{t("users.importSkipInbound")}</option>
                  {panelTags.map((pt) => <option key={pt} value={pt}>{pt}</option>)}
                </Select>
              </div>
            ))}
          </div>
        </Callout>
      )}
      {rows.length > 0 && (
        <div className="sk-table-wrap" style={{ marginTop: 12, maxHeight: 300, overflow: "auto" }}>
          <table className="sk-table">
            <thead>
              <tr>
                <th>{t("common.username")}</th>
                <th>{t("common.status")}</th>
                <th>{t("common.protocols")}</th>
                <th>{t("users.dataLimit")}</th>
                <th>{t("users.importConflict")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 50).map((r, i) => (
                <tr key={`${r.username}-${i}`}>
                  <td>{r.username}</td>
                  <td>{t(`users.status.${r.status}`, r.status)}</td>
                  <td className="sk-faint" style={{ fontSize: 11 }}>{r.proxies ? Object.keys(r.proxies).join(", ") : "—"}</td>
                  <td className="sk-faint" style={{ fontSize: 11 }}>{r.data_limit ? formatBytes(r.data_limit) : t("users.unlimited")}</td>
                  <td className="sk-faint">{r.conflict ? t(`users.importConflict.${r.conflict}`, r.conflict) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  );
};
