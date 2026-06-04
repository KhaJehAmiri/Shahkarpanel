import { FC, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { InboundsByProtocol, UserItem, UsersResponse } from "../api/types";
import { useFetch } from "../lib/useFetch";
import { formatBytes, formatDate, relativeExpiry, statusTone, usagePct } from "../lib/format";
import { PageHeader } from "../components/Shell";
import {
  Button, Callout, Card, Checkbox, CopyField, Drawer, EmptyState, Field, Input, Modal, Pill, Select,
  SkeletonRows, Toggle, UsageBar, useToast,
} from "../components/ui";
import { QR } from "../components/QR";
import { absoluteUrl } from "../lib/url";
import { copyToClipboard } from "../lib/clipboard";
import { IcEdit, IcExternal, IcEye, IcPlus, IcRefresh, IcShare, IcTrash } from "../components/icons";
import { UserTemplatesPanel } from "../components/UserTemplates";
import { useApp } from "../context/AppContext";

const PAGE = 12;
const STATUSES = ["active", "disabled", "expired", "limited", "on_hold"];
const SS_METHODS = ["chacha20-ietf-poly1305", "aes-256-gcm", "aes-128-gcm"];
const FLOWS = [
  { v: "", label: "none (recommended)" },
  { v: "xtls-rprx-vision", label: "xtls-rprx-vision" },
];
const PROTO_LABEL: Record<string, string> = { vless: "VLESS", vmess: "VMess", trojan: "Trojan", shadowsocks: "Shadowsocks", wireguard: "WireGuard" };

export const Users: FC = () => {
  const { t, i18n } = useTranslation();
  const { admin } = useApp();
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
        description={t("users.description")}
        actions={<>
          <Button variant="ghost" onClick={reload}><IcRefresh className="nx-ico" /></Button>
          <Button variant="primary" onClick={() => setShowCreate(true)}><IcPlus className="nx-ico" /> {t("common.create")}</Button>
        </>}
      />

      {admin?.is_sudo && <UserTemplatesPanel />}

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
                          <div className="nx-row" style={{ justifyContent: "flex-end", gap: 6, flexWrap: "nowrap" }}>
                            <Button size="sm" variant="ghost" title={t("common.view")} onClick={() => setViewUser(u)}><IcEye className="nx-ico" /></Button>
                            <Button size="sm" variant="ghost" title={t("common.edit")} onClick={() => setEditUser(u)}><IcEdit className="nx-ico" /></Button>
                            <Toggle on={u.status !== "disabled"} onChange={() => toggleUser(u)} />
                            <Button variant="danger" size="sm" title={t("common.delete")} onClick={() => removeUser(u)}><IcTrash className="nx-ico" /></Button>
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
  const { admin } = useApp();
  const toast = useToast();
  const inbounds = useFetch<InboundsByProtocol>(() => api.get("/inbounds"), []);
  const templates = useFetch<{ id: number; name?: string }[]>(
    () => (admin?.is_sudo ? api.get("/user_template") : Promise.resolve([])),
    [admin?.is_sudo],
  );
  const [templateId, setTemplateId] = useState("");

  const [username, setUsername] = useState(user?.username || "");
  const [dataGb, setDataGb] = useState(user?.data_limit ? (user.data_limit / 1024 ** 3).toString() : "");
  const [unlimited, setUnlimited] = useState(!user?.data_limit);
  const [expireDate, setExpireDate] = useState(user?.expire ? new Date(user.expire * 1000).toISOString().slice(0, 10) : "");
  const [noExpire, setNoExpire] = useState(!user?.expire);
  const [status, setStatus] = useState(
    user && ["active", "on_hold", "disabled", "limited", "expired"].includes(user.status) ? user.status : "active"
  );
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
    // WireGuard is a first-class protocol that is *not* an Xray inbound, so it
    // never comes back from /inbounds. Surface it as a synthetic toggle: the
    // server generates the peer keypair + allocates the IP automatically.
    next["wireguard"] = {
      enabled: mode === "edit" ? userProtos.includes("wireguard") : false,
      tags: [],
      flow: "",
      method: "",
    };
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
    if (mode === "create" && templateId) {
      if (!username.trim()) { toast.push(t("common.username"), "error"); return; }
      setBusy(true);
      try {
        await api.post("/user/from-template", {
          username: username.trim(),
          template_id: parseInt(templateId, 10),
          status: status === "on_hold" ? "on_hold" : "active",
        });
        toast.push(t("common.created"), "success");
        onDone();
      } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
      return;
    }
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
        <Button variant="primary" disabled={busy || (mode === "create" && !username.trim()) || (mode === "create" && !!templateId && !username.trim())} onClick={submit}>
          {mode === "create" ? t("common.create") : t("common.save")}
        </Button>
      </>}
    >
      <div className="nx-stack">
        {mode === "create" && templateId ? (
          <Callout tone="info">{t("users.templateHint")}</Callout>
        ) : null}
        {mode === "create" && (
          <>
            <Field label={t("common.username")} hint="a-z, 0-9, _ (3–32)">
              <Input value={username} onChange={(e: any) => setUsername(e.target.value)} autoFocus />
            </Field>
            {templates.data && templates.data.length > 0 && (
              <Field label={t("users.template")}>
                <select className="nx-input" value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
                  <option value="">{t("users.noTemplate")}</option>
                  {templates.data.map((tpl) => (
                    <option key={tpl.id} value={tpl.id}>{tpl.name || `#${tpl.id}`}</option>
                  ))}
                </select>
              </Field>
            )}
          </>
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
                        <span className="nx-faint" style={{ fontSize: 11 }}>{p === "wireguard" ? t("users.wgNativePeer") : `${inbounds.data?.[p]?.length || 0} inbound(s)`}</span>
                      </div>
                    </div>
                    {v.enabled && (
                      <div style={{ marginTop: 10, paddingInlineStart: 28 }}>
                        {p === "wireguard" ? (
                          <div className="nx-faint" style={{ fontSize: 12, marginBottom: 8 }}>{t("users.wgHint")}</div>
                        ) : (
                        <div className="nx-row" style={{ gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
                          {inbounds.data?.[p]?.map((i) => (
                            <button key={i.tag} type="button" className={`nx-btn sm ${v.tags.includes(i.tag) ? "primary" : ""}`} onClick={() => toggleTag(p, i.tag)}>
                              {v.tags.includes(i.tag) ? "✓ " : ""}{i.tag} <span style={{ opacity: 0.6 }}>:{i.port}</span>
                            </button>
                          ))}
                        </div>
                        )}
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
const proxyKind = (link: string): string => {
  const i = link.indexOf("://");
  return i === -1 ? "link" : link.slice(0, i).toUpperCase();
};

const remainingPct = (used: number, limit: number | null | undefined) => {
  if (!limit || limit <= 0) return null;
  return Math.max(0, Math.min(100, 100 - (used / limit) * 100));
};

const UserDetail: FC<{ username: string; onClose: () => void; onEdit: () => void }> = ({ username, onClose, onEdit }) => {
  const { t, i18n } = useTranslation();
  const toast = useToast();
  const { data, loading } = useFetch<UserItem>(() => api.get(`/user/${encodeURIComponent(username)}`), [username]);
  const [tab, setTab] = useState<"subscription" | "configs">("subscription");
  const [activeLink, setActiveLink] = useState(0);

  const pct = data ? usagePct(data.used_traffic, data.data_limit) : 0;
  const remaining = data ? remainingPct(data.used_traffic, data.data_limit) : null;
  const subUrl = absoluteUrl(data?.subscription_url);
  const rawLinks = data?.links || [];
  const links = rawLinks.map((l) => absoluteUrl(l));
  const hasWireguard = !!data?.proxies && "wireguard" in data.proxies;
  const wgUrl = subUrl ? `${subUrl.replace(/\/$/, "")}/wireguard` : "";

  const initials = username.slice(0, 2).toUpperCase();

  const share = async (url: string) => {
    if (navigator.share) {
      try { await navigator.share({ title: `NexusPanel — ${username}`, url }); return; } catch { /* user cancelled */ }
    }
    const ok = await copyToClipboard(url);
    toast.push(ok ? "Link copied — share it" : "Copy failed", ok ? "success" : "error");
  };

  return (
    <Drawer open title={t("users.title")} onClose={onClose}>
      {loading || !data ? <SkeletonRows rows={6} cols={1} /> : (
        <>
          {/* Hero */}
          <div className="nx-user-hero">
            <div className="nx-avatar">{initials}</div>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div className="nx-user-hero-name nx-truncate">{data.username}</div>
              <div className="nx-user-hero-meta">
                <Pill tone={statusTone(data.status)} dot>{t(`users.status.${data.status}`, data.status)}</Pill>
                {data.admin ? <span style={{ marginInlineStart: 8 }}>by {data.admin.username}</span> : null}
              </div>
            </div>
            <div className="nx-row" style={{ gap: 8, flexShrink: 0 }}>
              <Button size="sm" variant="ghost" onClick={async () => {
                if (!confirm(t("users.resetUsageConfirm"))) return;
                try {
                  await api.post(`/user/${encodeURIComponent(username)}/reset`);
                  toast.push(t("common.saved"), "success");
                  onClose();
                } catch (e: any) { toast.push(e.message, "error"); }
              }}>{t("users.resetUsage")}</Button>
              <Button size="sm" variant="ghost" onClick={async () => {
                if (!confirm(t("users.revokeSubConfirm"))) return;
                try {
                  await api.post(`/user/${encodeURIComponent(username)}/revoke_sub`);
                  toast.push(t("common.saved"), "success");
                  onClose();
                } catch (e: any) { toast.push(e.message, "error"); }
              }}>{t("users.revokeSub")}</Button>
              <Button size="sm" onClick={onEdit}><IcEdit className="nx-ico" /> {t("common.edit")}</Button>
            </div>
          </div>

          {/* Stat grid */}
          <div className="nx-statgrid" style={{ marginBottom: 18 }}>
            <div className="nx-statbox">
              <div className="nx-statbox-k">{t("users.used")}</div>
              <div className="nx-statbox-v">{formatBytes(data.used_traffic)}</div>
              {data.data_limit ? <div className="nx-faint" style={{ fontSize: 11, marginTop: 4 }}>{t("users.of")} {formatBytes(data.data_limit)}</div> : <div className="nx-faint" style={{ fontSize: 11, marginTop: 4 }}>{t("users.unlimited")}</div>}
            </div>
            <div className="nx-statbox">
              <div className="nx-statbox-k">{t("users.remaining")}</div>
              <div className="nx-statbox-v">{remaining !== null ? `${remaining.toFixed(0)}%` : "∞"}</div>
              {data.data_limit ? <div style={{ marginTop: 8 }}><UsageBar pct={pct} /></div> : null}
            </div>
            <div className="nx-statbox">
              <div className="nx-statbox-k">{t("users.expire")}</div>
              <div className="nx-statbox-v">{data.expire ? formatDate(data.expire, i18n.language) : t("users.never")}</div>
              {data.expire ? <div className="nx-faint" style={{ fontSize: 11, marginTop: 4 }}>{(() => { const r = relativeExpiry(data.expire); return r.days !== null && r.days < 0 ? t("users.expired") : r.text; })()}</div> : null}
            </div>
            <div className="nx-statbox">
              <div className="nx-statbox-k">{t("users.online")}</div>
              <div className="nx-statbox-v">{data.online_at ? formatDate(new Date(data.online_at).getTime() / 1000, i18n.language) : "—"}</div>
            </div>
          </div>

          {/* Tabs */}
          {(subUrl || links.length > 0) && (
            <>
              <div className="nx-tabs">
                {subUrl && <button className={`nx-tab ${tab === "subscription" ? "active" : ""}`} onClick={() => setTab("subscription")}>{t("users.subscription")}</button>}
                {links.length > 0 && <button className={`nx-tab ${tab === "configs" ? "active" : ""}`} onClick={() => setTab("configs")}>{t("users.configs")} · {links.length}</button>}
              </div>

              {tab === "subscription" && subUrl && (
                <div className="nx-stack" style={{ alignItems: "stretch", gap: 14 }}>
                  <div className="nx-center"><div className="nx-qr-frame"><QR value={subUrl} size={200} /></div></div>
                  <CopyField label={t("users.subUrl")} value={subUrl} />
                  <div className="nx-share-row">
                    <a className="nx-btn" href={subUrl} target="_blank" rel="noreferrer"><IcExternal className="nx-ico" /> {t("users.open")}</a>
                    <Button onClick={() => share(subUrl)}><IcShare className="nx-ico" /> {t("users.share")}</Button>
                  </div>
                  {hasWireguard && wgUrl && (
                    <a className="nx-btn" href={wgUrl} download={`${data.username}.conf`}>
                      <IcExternal className="nx-ico" /> {t("users.downloadWireguard")}
                    </a>
                  )}
                </div>
              )}

              {tab === "configs" && links.length > 0 && (
                <div className="nx-stack" style={{ gap: 12 }}>
                  <div className="nx-pager">
                    {links.map((l, i) => (
                      <button key={i} type="button" className={`nx-chip ${activeLink === i ? "active" : ""}`} onClick={() => setActiveLink(i)}>{proxyKind(l)} · #{i + 1}</button>
                    ))}
                  </div>
                  <div className="nx-center"><div className="nx-qr-frame"><QR value={links[activeLink]} size={170} /></div></div>
                  <CopyField label={proxyKind(links[activeLink])} value={links[activeLink]} multiline />
                </div>
              )}
            </>
          )}
        </>
      )}
    </Drawer>
  );
};
