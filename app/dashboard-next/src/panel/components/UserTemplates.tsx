import { FC, useState } from "react";
import {
  bytesToDataLimitValue, dataLimitToBytes, detectDataLimitUnit, type DataLimitUnit,
} from "../lib/data-limit";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useFetch } from "../lib/useFetch";
import { formatBytes } from "../lib/format";
import {
  Button, Card, EmptyState, Field, Input, Modal, Select, SkeletonRows, useToast,
} from "./ui";
import { IcPlus, IcTrash, IcEdit } from "./icons";

export interface UserTemplateRow {
  id: number;
  name?: string | null;
  data_limit?: number | null;
  expire_duration?: number | null;
  username_prefix?: string | null;
  username_suffix?: string | null;
  inbounds?: Record<string, string[]>;
}

export const UserTemplatesPanel: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const [show, setShow] = useState(false);
  const [edit, setEdit] = useState<UserTemplateRow | null>(null);
  const { data, loading, error, reload } = useFetch<UserTemplateRow[]>(() => api.get("/user_template"), []);

  const remove = async (row: UserTemplateRow) => {
    if (!confirm(t("common.confirmDelete"))) return;
    try {
      await api.del(`/user_template/${row.id}`);
      toast.push(t("common.deleted"), "success");
      reload();
    } catch (e: any) {
      toast.push(e.message, "error");
    }
  };

  return (
    <Card style={{ marginBottom: 16 }}>
      <div className="nx-row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
        <div>
          <b>{t("users.templates")}</b>
          <div className="nx-faint" style={{ fontSize: 12, marginTop: 4 }}>{t("users.templatesDesc")}</div>
        </div>
        <Button variant="primary" size="sm" onClick={() => setShow(true)}><IcPlus className="nx-ico" /> {t("users.addTemplate")}</Button>
      </div>
      {loading ? <SkeletonRows rows={2} cols={3} />
        : error ? <EmptyState title={t("common.error")} desc={error} />
        : !data?.length ? <div className="nx-faint" style={{ fontSize: 13 }}>{t("common.noData")}</div>
        : (
          <div className="nx-table-wrap">
            <table className="nx-table">
              <thead><tr>
                <th>{t("common.name")}</th><th>{t("users.dataLimit")}</th><th>{t("users.expire")}</th>
                <th style={{ textAlign: "end" }}>{t("common.actions")}</th>
              </tr></thead>
              <tbody>
                {data.map((row) => (
                  <tr key={row.id}>
                    <td style={{ fontWeight: 600 }}>{row.name || `#${row.id}`}</td>
                    <td>{row.data_limit ? formatBytes(row.data_limit) : t("users.unlimited")}</td>
                    <td>{row.expire_duration ? `${Math.round(row.expire_duration / 86400)}d` : "—"}</td>
                    <td>
                      <div className="nx-row" style={{ justifyContent: "flex-end", gap: 6 }}>
                        <Button size="sm" variant="ghost" onClick={() => setEdit(row)}><IcEdit className="nx-ico" /></Button>
                        <Button size="sm" variant="danger" onClick={() => remove(row)}><IcTrash className="nx-ico" /></Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      {show && <TemplateFormModal onClose={() => setShow(false)} onDone={() => { setShow(false); reload(); }} />}
      {edit && <TemplateFormModal row={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); reload(); }} />}
    </Card>
  );
};

const TemplateFormModal: FC<{ row?: UserTemplateRow; onClose: () => void; onDone: () => void }> = ({ row, onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [name, setName] = useState(row?.name || "");
  const [dataLimitUnit, setDataLimitUnit] = useState<DataLimitUnit>(
    row?.data_limit ? detectDataLimitUnit(row.data_limit) : "MB",
  );
  const [dataLimitValue, setDataLimitValue] = useState(
    row?.data_limit ? bytesToDataLimitValue(row.data_limit, detectDataLimitUnit(row.data_limit)) : "",
  );
  const [expireDays, setExpireDays] = useState(row?.expire_duration ? String(Math.round(row.expire_duration / 86400)) : "");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      const body: Record<string, unknown> = {
        name: name.trim(),
        data_limit: dataLimitValue ? dataLimitToBytes(dataLimitValue, dataLimitUnit) : 0,
        expire_duration: expireDays ? parseInt(expireDays, 10) * 86400 : 0,
        inbounds: row?.inbounds || {},
      };
      if (row) {
        await api.put(`/user_template/${row.id}`, body);
      } else {
        await api.post("/user_template", body);
      }
      toast.push(row ? t("common.saved") : t("common.created"), "success");
      onDone();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open title={row ? t("users.editTemplate") : t("users.addTemplate")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !name.trim()} onClick={submit}>{row ? t("common.save") : t("common.create")}</Button></>}>
      <div className="nx-stack">
        <Field label={t("common.name")}><Input value={name} onChange={(e: any) => setName(e.target.value)} autoFocus /></Field>
        <Field label={t("users.dataLimit")} hint="0 = unlimited">
          <div className="nx-row" style={{ gap: 8 }}>
            <Input type="number" min="0" step={dataLimitUnit === "MB" ? "1" : "0.001"} value={dataLimitValue} onChange={(e: any) => setDataLimitValue(e.target.value)} style={{ flex: 1 }} />
            <Select value={dataLimitUnit} onChange={(e: any) => setDataLimitUnit(e.target.value as DataLimitUnit)} style={{ width: 88 }}>
              <option value="MB">MB</option>
              <option value="GB">GB</option>
            </Select>
          </div>
        </Field>
        <Field label={`${t("users.expire")} (days)`} hint="0 = none"><Input type="number" min="0" value={expireDays} onChange={(e: any) => setExpireDays(e.target.value)} /></Field>
      </div>
    </Modal>
  );
};
