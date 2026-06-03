import { FC, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { InboundsByProtocol, UserItem, UsersResponse } from "../api/types";
import { useFetch } from "../lib/useFetch";
import { formatBytes, formatDate, relativeExpiry, statusTone, usagePct } from "../lib/format";
import { PageHeader } from "../components/Shell";
import {
  Button, Card, Checkbox, CopyField, Drawer, EmptyState, Field, Input, Modal, Pill, Select,
  SkeletonRows, Toggle, UsageBar, useToast,
} from "../components/ui";
import { QR } from "../components/QR";
import { IcPlus, IcRefresh, IcTrash } from "../components/icons";

const PAGE = 12;
const STATUSES = ["active", "disabled", "expired", "limited", "on_hold"];
const SS_METHODS = ["chacha20-ietf-poly1305", "aes-256-gcm", "aes-128-gcm"];
const FLOWS = [
  { v: "", label: "none (recommended)" },
  { v: "xtls-rprx-vision", label: "xtls-rprx-vision" },
];
const PROTO_LABEL: Record<string, string> = { vless: "VLESS", vmess: "VMess", trojan: "Trojan", shadowsocks: "Shadowsocks" };

export const Users: FC = () => {
  const { t, i18n } = useTranslation();
  const toast = useToast();
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [editUser, setEditUser] = useState<UserItem | null>(null);
  const [viewUser, setViewUser] = useState<UserItem | null>(null);

  const query = useMemo(() => {
    const p = new URLSearchParams();
    p.set("offset", String(page * PAGE));
    p.set("limit", String(PAGE));
    if (search.trim()) p.set("search", search.trim());
    if (statusFilter) p.set("status", statusFilter);
    return p.toString();
  }, [page, search, statusFilter]);

  const { data, loading, error, reload } = useFetch<UsersResponse>(() => api.get(`/users?${query}`), [query]);
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));

  const toggleUser = async (u: UserItem) => {
    const next = u.status === "disabled" ? "active" : "disabled";
    try { await api.put(`/user/${encodeURIComponent(u.username)}`, { status: next }); toast.push(t("common.saved"), "success"); reload(); }
    catch (e: any) { toast.push(e.message, "error"); }
  };
  const removeUser = async (u: UserItem) => {
    if (!confirm(t("common.confirmDelete"))) return;
    try { await api.del(`/user/${encodeURIComponent(u.username)}`); toast.push(t("common.deleted"), "success"); reload(); }
    catch (e: any) { toast.push(e.message, "error"); }
  };

  return (
    <div>
      <PageHeader
        title={t("users.title")}
        subtitle={t("users.subtitle")}
        actions={<>
          <Button variant="ghost" onClick={reload}><IcRefresh className="nx-ico" /></Button>
          <Button variant="primary" onClick={() => setShowCreate(true)}><IcPlus className="nx-ico" /> {t("common.create")}</Button>
        </>}
      />

      <Card style={{ marginBottom: 16 }}>
        <div className="nx-row">
          <Input placeholder={t("users.searchPlaceholder")} value={search} onChange={(e: any) => { setSearch(e.target.value); setPage(0); }} style={{ maxWidth: 320 }} />
          <Select value={statusFilter} onChange={(e: any) => { setStatusFilter(e.target.value); setPage(0); }} style={{ maxWidth: 200 }}>
            <option value="">{t("common.all")} — {t("common.status")}</option>
            {STATUSES.map((s) => <option key={s} value={s}>{t(`users.status.${s}`)}</option>)}
          </Select>
          <div className="nx-spacer" />
          <span className="nx-faint" style={{ fontSize: 12 }}>{t("common.total")}: {total}</span>
        </div>
      </Card>

      <Card pad0>
        {loading ? <div style={{ padding: 20 }}><SkeletonRows rows={6} cols={5} /></div>
          : error ? <EmptyState title={t("common.error")} desc={error} action={<Button onClick={reload}>{t("common.retry")}</Button>} />
          : !data?.users.length ? <EmptyState title={t("common.noData")} action={<Button variant="primary" onClick={() => setShowCreate(true)}><IcPlus className="nx-ico" /> {t("common.create")}</Button>} />
          : (
            <div className="nx-table-wrap">
              <table className="nx-table">
                <thead><tr>
                  <th>{t("common.username")}</th><th>{t("common.status")}</th><th>Protocols</th>
                  <th>{t("users.used")}</th><th>{t("users.expire")}</th><th style={{ textAlign: "end" }}>{t("common.actions")}</th>
                </tr></thead>
                <tbody>
                  {data.users.map((u) => {
                    const pct = usagePct(u.used_traffic, u.data_limit);
                    const protos = u.proxies ? Object.keys(u.proxies) : [];
                    return (
                      <tr key={u.username} style={{ cursor: "pointer" }} onClick={() => setViewUser(u)}>
                        <td style={{ fontWeight: 600 }}>{u.username}{u.note ? <div className="nx-faint" style={{ fontWeight: 400, fontSize: 11 }}>{u.note}</div> : null}</td>
                        <td><Pill tone={statusTone(u.status)} dot>{t(`users.status.${u.status}`, u.status)}</Pill></td>
                        <td><div className="nx-row" style={{ gap: 4 }}>{protos.length ? protos.map((p) => <Pill key={p} tone="accent">{PROTO_LABEL[p] || p}</Pill>) : <span className="nx-faint">—</span>}</div></td>
                        <td style={{ minWidth: 170 }}>
                          <div style={{ fontSize: 12 }}>{formatBytes(u.used_traffic)} / {u.data_limit ? formatBytes(u.data_limit) : t("users.unlimited")}</div>
                          {u.data_limit ? <div style={{ marginTop: 5 }}><UsageBar pct={pct} /></div> : null}
                        </td>
                        <td>{u.expire ? formatDate(u.expire, i18n.language) : <span className="nx-faint">{t("users.never")}</span>}</td>
                        <td onClick={(e) => e.stopPropagation()}>
                          <div className="nx-row" style={{ justifyContent: "flex-end", gap: 8 }}>
                            <Button size="sm" onClick={() => setEditUser(u)}>{t("common.edit")}</Button>
                            <Toggle on={u.status !== "disabled"} onChange={() => toggleUser(u)} />
                            <Button variant="danger" size="sm" onClick={() => removeUser(u)}><IcTrash className="nx-ico" /></Button>
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
          <span className="nx-faint" style={{ fontSize: 12 }}>{t("users.showing", { from: page * PAGE + 1, to: Math.min((page + 1) * PAGE, total), total })}</span>
          <div className="nx-row">
            <Button size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>{t("users.prev")}</Button>
            <span className="nx-faint" style={{ fontSize: 12 }}>{page + 1} / {pages}</span>
            <Button size="sm" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>{t("users.next")}</Button>
          </div>
        </div>
      )}

      {showCreate && <UserFormModal mode="create" onClose={() => setShowCreate(false)} onDone={() => { setShowCreate(false); reload(); }} />}
      {editUser && <UserFormModal mode="edit" user={editUser} onClose={() => setEditUser(null)} onDone={() => { setEditUser(null); reload(); }} />}
      {viewUser && <UserDetail username={viewUser.username} onClose={() => setViewUser(null)} onEdit={() => { setEditUser(viewUser); setViewUser(null); }} />}
    </div>
  );
};

/* --------------------------- shared user form --------------------------- */
type ProtoState = { enabled: boolean; tags: string[]; flow: string; method: string };

const UserFormModal: FC<{ mode: "create" | "edit"; user?: UserItem; onClose: () => void; onDone: () => void }> = ({ mode, user, onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const inbounds = useFetch<InboundsByProtocol>(() => api.get("/inbounds"), []);

  const [username, setUsername] = useState(user?.username || "");
  const [dataGb, setDataGb] = useState(user?.data_limit ? (user.data_limit / 1024 ** 3).toString() : "");
  const [unlimited, setUnlimited] = useState(!user?.data_limit);
  const [expireDate, setExpireDate] = useState(user?.expire ? new Date(user.expire * 1000).toISOString().slice(0, 10) : "");
  const [noExpire, setNoExpire] = useState(!user?.expire);
  const [status, setStatus] = useState(user && ["active", "on_hold", "disabled"].includes(user.status) ? user.status : "active");
  const [reset, setReset] = useState(user?.data_limit_reset_strategy || "no_reset");
  const [note, setNote] = useState(user?.note || "");
  const [protos, setProtos] = useState<Record<string, ProtoState>>({});
  const [busy, setBusy] = useState(false);

  // Initialize protocol state once inbounds + user are known.
  useEffect(() => {
    if (!inbounds.data) return;
    const next: Record<string, ProtoState> = {};
    const userProtos = user?.proxies ? Object.keys(user.proxies) : [];
    Object.keys(inbounds.data).forEach((proto, idx) => {
      const tags = inbounds.data![proto].map((i) => i.tag);
      const enabled = mode === "edit" ? userProtos.includes(proto) : idx === 0;
      const selected = user?.inbounds?.[proto] || tags;
      next[proto] = {
        enabled,
        tags: enabled ? selected.filter((s) => tags.includes(s)) : tags,
        flow: user?.proxies?.[proto]?.flow || "",
        method: user?.proxies?.[proto]?.method || "chacha20-ietf-poly1305",
      };
    });
    setProtos(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inbounds.data]);

  const setProto = (p: string, patch: Partial<ProtoState>) => setProtos((s) => ({ ...s, [p]: { ...s[p], ...patch } }));
  const toggleTag = (p: string, tag: string) => setProtos((s) => {
    const cur = s[p];
    const tags = cur.tags.includes(tag) ? cur.tags.filter((x) => x !== tag) : [...cur.tags, tag];
    return { ...s, [p]: { ...cur, tags } };
  });

  const enabledProtos = Object.entries(protos).filter(([, v]) => v.enabled);

  const submit = async () => {
    if (!enabledProtos.length) { toast.push("Select at least one protocol", "error"); return; }
    setBusy(true);
    try {
      const proxies: Record<string, any> = {};
      const inb: Record<string, string[]> = {};
      enabledProtos.forEach(([p, v]) => {
        const s: any = {};
        if (p === "vless") s.flow = v.flow;
        if (p === "shadowsocks") s.method = v.method;
        proxies[p] = s;
        inb[p] = v.tags;
      });
      const body: any = {
        proxies,
        inbounds: inb,
        data_limit: unlimited || !dataGb ? 0 : Math.round(parseFloat(dataGb) * 1024 ** 3),
        data_limit_reset_strategy: reset,
        note: note || "",
      };
      if (status === "on_hold") {
        body.status = "on_hold";
        body.on_hold_expire_duration = !noExpire && expireDate
          ? Math.max(3600, Math.floor((new Date(expireDate).getTime() - Date.now()) / 1000))
          : 30 * 86400;
        body.expire = 0;
      } else {
        body.status = status;
        body.expire = noExpire || !expireDate ? 0 : Math.floor(new Date(expireDate).getTime() / 1000);
      }

      if (mode === "create") {
        body.username = username.trim();
        await api.post("/user", body);
        toast.push(t("common.created"), "success");
      } else {
        await api.put(`/user/${encodeURIComponent(user!.username)}`, body);
        toast.push(t("common.saved"), "success");
      }
      onDone();
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  const preset = (days: number) => { setNoExpire(false); setExpireDate(new Date(Date.now() + days * 86400000).toISOString().slice(0, 10)); };

  return (
    <Modal
      open
      title={mode === "create" ? t("common.create") : `${t("common.edit")} — ${user?.username}`}
      onClose={onClose}
      footer={<>
        <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || (mode === "create" && !username.trim())} onClick={submit}>
          {mode === "create" ? t("common.create") : t("common.save")}
        </Button>
      </>}
    >
      <div className="nx-stack">
        {mode === "create" && (
          <Field label={t("common.username")} hint="a-z, 0-9, _ (3–32)">
            <Input value={username} onChange={(e: any) => setUsername(e.target.value)} autoFocus />
          </Field>
        )}

        {/* Protocols (x-ui style) */}
        <div className="nx-field">
          <label className="nx-label">Protocols & inbounds</label>
          {inbounds.loading ? <SkeletonRows rows={2} cols={1} />
            : !Object.keys(protos).length ? <div className="nx-faint" style={{ fontSize: 12 }}>{t("common.noData")}</div>
            : (
              <div className="nx-stack" style={{ gap: 8 }}>
                {Object.entries(protos).map(([p, v]) => (
                  <div key={p} className={`nx-proto ${v.enabled ? "on" : ""}`}>
                    <div className="nx-proto-head" onClick={() => setProto(p, { enabled: !v.enabled })}>
                      <div className="nx-row" style={{ gap: 10 }}>
                        <Checkbox checked={v.enabled} />
                        <b>{PROTO_LABEL[p] || p}</b>
                        <span className="nx-faint" style={{ fontSize: 11 }}>{inbounds.data?.[p].length} inbound(s)</span>
                      </div>
                    </div>
                    {v.enabled && (
                      <div style={{ marginTop: 10, paddingInlineStart: 28 }}>
                        <div className="nx-row" style={{ gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
                          {inbounds.data?.[p].map((i) => (
                            <button key={i.tag} type="button" className={`nx-btn sm ${v.tags.includes(i.tag) ? "primary" : ""}`} onClick={() => toggleTag(p, i.tag)}>
                              {v.tags.includes(i.tag) ? "✓ " : ""}{i.tag} <span style={{ opacity: 0.6 }}>:{i.port}</span>
                            </button>
                          ))}
                        </div>
                        {p === "vless" && (
                          <div className="nx-row" style={{ gap: 8 }}>
                            <span className="nx-faint" style={{ fontSize: 12 }}>flow</span>
                            <Select value={v.flow} onChange={(e: any) => setProto(p, { flow: e.target.value })} style={{ maxWidth: 220 }}>
                              {FLOWS.map((f) => <option key={f.v} value={f.v}>{f.label}</option>)}
                            </Select>
                          </div>
                        )}
                        {p === "shadowsocks" && (
                          <div className="nx-row" style={{ gap: 8 }}>
                            <span className="nx-faint" style={{ fontSize: 12 }}>method</span>
                            <Select value={v.method} onChange={(e: any) => setProto(p, { method: e.target.value })} style={{ maxWidth: 260 }}>
                              {SS_METHODS.map((m) => <option key={m} value={m}>{m}</option>)}
                            </Select>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
        </div>

        {/* Limits */}
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label={`${t("users.dataLimit")} (GB)`}>
            <div className="nx-row" style={{ gap: 8 }}>
              <Input type="number" min="0" step="0.1" value={unlimited ? "" : dataGb} disabled={unlimited} placeholder="∞" onChange={(e: any) => setDataGb(e.target.value)} />
              <label className="nx-row" style={{ gap: 6, fontSize: 12, whiteSpace: "nowrap" }}>
                <Checkbox checked={unlimited} onChange={() => setUnlimited((u) => !u)} /> ∞
              </label>
            </div>
          </Field>
          <Field label={t("billing.invoiceStatus")}>
            <Select value={status} onChange={(e: any) => setStatus(e.target.value)}>
              <option value="active">{t("users.status.active")}</option>
              <option value="on_hold">{t("users.status.on_hold")}</option>
              {mode === "edit" && <option value="disabled">{t("users.status.disabled")}</option>}
            </Select>
          </Field>
        </div>

        {/* Expiry */}
        <Field label={t("users.expire")}>
          <div className="nx-row" style={{ gap: 8 }}>
            <Input type="date" value={noExpire ? "" : expireDate} disabled={noExpire} onChange={(e: any) => setExpireDate(e.target.value)} style={{ maxWidth: 200 }} />
            <label className="nx-row" style={{ gap: 6, fontSize: 12, whiteSpace: "nowrap" }}>
              <Checkbox checked={noExpire} onChange={() => setNoExpire((u) => !u)} /> {t("users.never")}
            </label>
            <div className="nx-row" style={{ gap: 4 }}>
              {[30, 60, 90].map((d) => <Button key={d} size="sm" variant="ghost" onClick={() => preset(d)}>{d}d</Button>)}
            </div>
          </div>
        </Field>

        <div className="nx-row" style={{ gap: 12 }}>
          <Field label="Reset">
            <Select value={reset} onChange={(e: any) => setReset(e.target.value)}>
              {["no_reset", "day", "week", "month", "year"].map((r) => <option key={r} value={r}>{r}</option>)}
            </Select>
          </Field>
          <Field label={`Note (${t("common.optional")})`}><Input value={note} onChange={(e: any) => setNote(e.target.value)} /></Field>
        </div>
      </div>
    </Modal>
  );
};

/* ----------------------------- user detail ----------------------------- */
const UserDetail: FC<{ username: string; onClose: () => void; onEdit: () => void }> = ({ username, onClose, onEdit }) => {
  const { t, i18n } = useTranslation();
  const { data, loading } = useFetch<UserItem>(() => api.get(`/user/${encodeURIComponent(username)}`), [username]);
  const [activeLink, setActiveLink] = useState(0);
  const pct = data ? usagePct(data.used_traffic, data.data_limit) : 0;
  const links = data?.links || [];

  return (
    <Drawer open title={username} onClose={onClose}>
      {loading || !data ? <SkeletonRows rows={5} cols={1} /> : (
        <div className="nx-stack" style={{ gap: 18 }}>
          <div className="nx-row" style={{ justifyContent: "space-between" }}>
            <Pill tone={statusTone(data.status)} dot>{t(`users.status.${data.status}`, data.status)}</Pill>
            <Button size="sm" onClick={onEdit}>{t("common.edit")}</Button>
          </div>

          <div>
            <div className="nx-row" style={{ justifyContent: "space-between", fontSize: 13 }}>
              <span className="nx-muted">{t("users.used")}</span>
              <span>{formatBytes(data.used_traffic)} / {data.data_limit ? formatBytes(data.data_limit) : t("users.unlimited")}</span>
            </div>
            {data.data_limit ? <div style={{ marginTop: 6 }}><UsageBar pct={pct} /></div> : null}
            <div className="nx-row" style={{ justifyContent: "space-between", fontSize: 13, marginTop: 10 }}>
              <span className="nx-muted">{t("users.expire")}</span>
              <span>{data.expire ? formatDate(data.expire, i18n.language) : t("users.never")}</span>
            </div>
          </div>

          {data.subscription_url && (
            <div className="nx-stack" style={{ alignItems: "center", gap: 10 }}>
              <QR value={data.subscription_url} />
              <CopyField label="Subscription URL" value={data.subscription_url} />
            </div>
          )}

          {links.length > 0 && (
            <div className="nx-field">
              <label className="nx-label">Configs ({links.length})</label>
              <div className="nx-row" style={{ gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
                {links.map((_, i) => (
                  <button key={i} type="button" className={`nx-btn sm ${activeLink === i ? "primary" : ""}`} onClick={() => setActiveLink(i)}>#{i + 1}</button>
                ))}
              </div>
              <div className="nx-stack" style={{ alignItems: "center", gap: 10 }}>
                <QR value={links[activeLink]} size={150} />
                <CopyField value={links[activeLink]} />
              </div>
            </div>
          )}
        </div>
      )}
    </Drawer>
  );
};
