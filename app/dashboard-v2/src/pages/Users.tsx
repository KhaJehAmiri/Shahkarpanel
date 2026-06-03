import { FC, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { UserItem, UsersResponse } from "../api/types";
import { useFetch } from "../lib/useFetch";
import { formatBytes, formatDate, relativeExpiry, statusTone, usagePct } from "../lib/format";
import { PageHeader } from "../components/Shell";
import {
  Button, Card, EmptyState, Field, Input, Modal, Pill, Select, SkeletonRows, Toggle, UsageBar, useToast,
} from "../components/ui";
import { IcPlus, IcRefresh, IcTrash } from "../components/icons";

const PAGE = 12;
const STATUSES = ["active", "disabled", "expired", "limited", "on_hold"];

export const Users: FC = () => {
  const { t, i18n } = useTranslation();
  const toast = useToast();
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  const query = useMemo(() => {
    const p = new URLSearchParams();
    p.set("offset", String(page * PAGE));
    p.set("limit", String(PAGE));
    if (search.trim()) p.set("search", search.trim());
    if (statusFilter) p.set("status", statusFilter);
    return p.toString();
  }, [page, search, statusFilter]);

  const { data, loading, error, reload } = useFetch<UsersResponse>(
    () => api.get(`/users?${query}`),
    [query]
  );

  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));

  const toggleUser = async (u: UserItem) => {
    const next = u.status === "disabled" ? "active" : "disabled";
    try {
      await api.put(`/user/${encodeURIComponent(u.username)}`, { status: next });
      toast.push(t("common.saved"), "success");
      reload();
    } catch (e: any) {
      toast.push(e.message, "error");
    }
  };

  const removeUser = async (u: UserItem) => {
    if (!confirm(t("common.confirmDelete"))) return;
    try {
      await api.del(`/user/${encodeURIComponent(u.username)}`);
      toast.push(t("common.deleted"), "success");
      reload();
    } catch (e: any) {
      toast.push(e.message, "error");
    }
  };

  return (
    <div>
      <PageHeader
        title={t("users.title")}
        subtitle={t("users.subtitle")}
        actions={
          <>
            <Button variant="ghost" onClick={reload}><IcRefresh className="nx-ico" /></Button>
            <Button variant="primary" onClick={() => setShowCreate(true)}>
              <IcPlus className="nx-ico" /> {t("common.create")}
            </Button>
          </>
        }
      />

      <Card style={{ marginBottom: 16 }}>
        <div className="nx-row">
          <Input
            placeholder={t("users.searchPlaceholder")}
            value={search}
            onChange={(e: any) => { setSearch(e.target.value); setPage(0); }}
            style={{ maxWidth: 320 }}
          />
          <Select value={statusFilter} onChange={(e: any) => { setStatusFilter(e.target.value); setPage(0); }} style={{ maxWidth: 200 }}>
            <option value="">{t("common.all")} — {t("common.status")}</option>
            {STATUSES.map((s) => <option key={s} value={s}>{t(`users.status.${s}`)}</option>)}
          </Select>
          <div className="nx-spacer" />
          <span className="nx-faint" style={{ fontSize: 12 }}>{t("common.total")}: {total}</span>
        </div>
      </Card>

      <Card pad0>
        {loading ? (
          <div style={{ padding: 20 }}><SkeletonRows rows={6} cols={5} /></div>
        ) : error ? (
          <EmptyState title={t("common.error")} desc={error} action={<Button onClick={reload}>{t("common.retry")}</Button>} />
        ) : !data?.users.length ? (
          <EmptyState title={t("common.noData")} />
        ) : (
          <div className="nx-table-wrap">
            <table className="nx-table">
              <thead>
                <tr>
                  <th>{t("common.username")}</th>
                  <th>{t("common.status")}</th>
                  <th>{t("users.used")}</th>
                  <th>{t("users.expire")}</th>
                  <th>{t("users.owner")}</th>
                  <th style={{ textAlign: "end" }}>{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {data.users.map((u) => {
                  const exp = relativeExpiry(u.expire);
                  const pct = usagePct(u.used_traffic, u.data_limit);
                  return (
                    <tr key={u.username}>
                      <td style={{ fontWeight: 600 }}>{u.username}{u.note ? <div className="nx-faint" style={{ fontWeight: 400, fontSize: 11 }}>{u.note}</div> : null}</td>
                      <td><Pill tone={statusTone(u.status)} dot>{t(`users.status.${u.status}`, u.status)}</Pill></td>
                      <td style={{ minWidth: 180 }}>
                        <div style={{ fontSize: 12 }}>{formatBytes(u.used_traffic)} / {u.data_limit ? formatBytes(u.data_limit) : t("users.unlimited")}</div>
                        {u.data_limit ? <div style={{ marginTop: 5 }}><UsageBar pct={pct} /></div> : null}
                      </td>
                      <td>{u.expire ? <span className={exp.days !== null && exp.days < 7 ? "" : ""}>{formatDate(u.expire, i18n.language)}</span> : <span className="nx-faint">{t("users.never")}</span>}</td>
                      <td className="nx-faint">{u.admin?.username || "—"}</td>
                      <td>
                        <div className="nx-row" style={{ justifyContent: "flex-end", gap: 8 }}>
                          <Toggle on={u.status !== "disabled"} onChange={() => toggleUser(u)} />
                          <Button variant="danger" size="sm" onClick={() => removeUser(u)} title={t("common.delete")}><IcTrash className="nx-ico" /></Button>
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

      {total > PAGE && (
        <div className="nx-row" style={{ justifyContent: "space-between", marginTop: 14 }}>
          <span className="nx-faint" style={{ fontSize: 12 }}>
            {t("users.showing", { from: page * PAGE + 1, to: Math.min((page + 1) * PAGE, total), total })}
          </span>
          <div className="nx-row">
            <Button size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>{t("users.prev")}</Button>
            <span className="nx-faint" style={{ fontSize: 12 }}>{page + 1} / {pages}</span>
            <Button size="sm" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>{t("users.next")}</Button>
          </div>
        </div>
      )}

      {showCreate && <CreateUser onClose={() => setShowCreate(false)} onDone={() => { setShowCreate(false); reload(); }} />}
    </div>
  );
};

const CreateUser: FC<{ onClose: () => void; onDone: () => void }> = ({ onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [username, setUsername] = useState("");
  const [dataGb, setDataGb] = useState("");
  const [days, setDays] = useState("30");
  const [protocol, setProtocol] = useState("");
  const [busy, setBusy] = useState(false);

  const inbounds = useFetch<Record<string, any[]>>(() => api.get("/inbounds"), []);
  const protocols = inbounds.data ? Object.keys(inbounds.data) : [];
  const chosen = protocol || protocols[0] || "vless";

  const submit = async () => {
    setBusy(true);
    try {
      const body: any = {
        username: username.trim(),
        status: "active",
        proxies: { [chosen]: {} },
        inbounds: {},
        data_limit: dataGb ? Math.round(parseFloat(dataGb) * 1024 ** 3) : 0,
        expire: days && parseInt(days) > 0 ? Math.floor(Date.now() / 1000) + parseInt(days) * 86400 : 0,
      };
      await api.post("/user", body);
      toast.push(t("common.created"), "success");
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
      title={t("common.create")}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="primary" disabled={busy || !username.trim()} onClick={submit}>{t("common.create")}</Button>
        </>
      }
    >
      <div className="nx-stack">
        <Field label={t("common.username")} hint="a-z, 0-9, _ (3–32)">
          <Input value={username} onChange={(e: any) => setUsername(e.target.value)} autoFocus />
        </Field>
        <Field label="Protocol">
          <Select value={chosen} onChange={(e: any) => setProtocol(e.target.value)}>
            {(protocols.length ? protocols : ["vless", "vmess", "trojan", "shadowsocks"]).map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </Select>
        </Field>
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label={`${t("users.dataLimit")} (GB)`} hint="0 = ∞"><Input type="number" min="0" value={dataGb} onChange={(e: any) => setDataGb(e.target.value)} /></Field>
          <Field label={`${t("users.expire")} (${t("billing.duration").toLowerCase()})`} hint="0 = ∞"><Input type="number" min="0" value={days} onChange={(e: any) => setDays(e.target.value)} /></Field>
        </div>
      </div>
    </Modal>
  );
};
