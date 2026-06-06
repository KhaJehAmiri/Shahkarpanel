import { FC, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { ImportPreviewResponse, ImportPreviewRow, InboundsByProtocol, UserItem, UsersResponse } from "../api/types";
import { useFetch } from "../lib/useFetch";
import { formatBytes, formatDate, relativeExpiry, statusTone, usagePct } from "../lib/format";
import {
  bytesToDataLimitValue, dataLimitToBytes, detectDataLimitUnit, type DataLimitUnit,
} from "../lib/data-limit";
import { PageHeader } from "../components/Shell";
import {
  Button, Callout, Card, Checkbox, CopyField, Drawer, EmptyState, Field, Input, Modal, Pill, Select,
  SkeletonRows, Toggle, UsageBar, useToast,
} from "../components/ui";
import { QR } from "../components/QR";
import { absoluteUrl } from "../lib/url";
import { copyToClipboard } from "../lib/clipboard";
import { IcClose, IcEdit, IcExternal, IcEye, IcPlus, IcRefresh, IcShare, IcTrash } from "../components/icons";
import { UserTemplatesPanel } from "../components/UserTemplates";
import { useApp } from "../context/AppContext";
import { useCopilot } from "../copilot/CopilotContext";

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
  const { consumeIntent } = useCopilot();
  const toast = useToast();
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [createWg, setCreateWg] = useState(false);
  const [editUser, setEditUser] = useState<UserItem | null>(null);
  const [viewUser, setViewUser] = useState<UserItem | null>(null);
  const [showImport, setShowImport] = useState(false);

  // The Copilot can deep-link straight into "create user" (optionally WireGuard).
  useEffect(() => {
    if (consumeIntent("create-wg-user")) { setCreateWg(true); setShowCreate(true); }
    else if (consumeIntent("create-user")) { setCreateWg(false); setShowCreate(true); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
          <Button variant="ghost" onClick={() => setShowImport(true)}>{t("users.import")}</Button>
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
                  <th>{t("common.username")}</th><th>{t("common.status")}</th><th>{t("common.protocols")}</th>
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

      {showCreate && <UserFormDrawer mode="create" presetWireguard={createWg} onClose={() => setShowCreate(false)} onDone={() => { setShowCreate(false); reload(); }} />}
      {editUser && <UserFormDrawer mode="edit" user={editUser} onClose={() => setEditUser(null)} onDone={() => { setEditUser(null); reload(); }} />}
      {showImport && <UserImportWizard onClose={() => setShowImport(false)} onDone={() => { setShowImport(false); reload(); }} />}
      {viewUser && <UserDetail username={viewUser.username} onClose={() => setViewUser(null)} onEdit={() => { setEditUser(viewUser); setViewUser(null); }} />}
    </div>
  );
};

/* --------------------------- shared user form --------------------------- */
type ProtoState = { enabled: boolean; tags: string[]; flow: string; method: string };

const UserFormDrawer: FC<{ mode: "create" | "edit"; user?: UserItem; presetWireguard?: boolean; onClose: () => void; onDone: () => void }> = ({ mode, user, presetWireguard, onClose, onDone }) => {
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
  const [dataLimitUnit, setDataLimitUnit] = useState<DataLimitUnit>(
    user?.data_limit ? detectDataLimitUnit(user.data_limit) : "MB",
  );
  const [dataLimitValue, setDataLimitValue] = useState(
    user?.data_limit ? bytesToDataLimitValue(user.data_limit, detectDataLimitUnit(user.data_limit)) : "",
  );
  const [unlimited, setUnlimited] = useState(!user?.data_limit);
  const [expireDate, setExpireDate] = useState(user?.expire ? new Date(user.expire * 1000).toISOString().slice(0, 10) : "");
  const [noExpire, setNoExpire] = useState(!user?.expire);
  const [status, setStatus] = useState(
    user && ["active", "on_hold", "disabled", "limited", "expired"].includes(user.status) ? user.status : "active"
  );
  const [reset, setReset] = useState(user?.data_limit_reset_strategy || "no_reset");
  const [note, setNote] = useState(user?.note || "");
  const [protos, setProtos] = useState<Record<string, ProtoState>>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
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
      enabled: mode === "edit" ? userProtos.includes("wireguard") : !!presetWireguard,
      tags: [],
      flow: "",
      method: "",
    };
    setProtos(next);
    const exp: Record<string, boolean> = {};
    Object.entries(next).forEach(([p, v]) => { exp[p] = v.enabled; });
    setExpanded(exp);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inbounds.data]);

  const setProto = (p: string, patch: Partial<ProtoState>) => {
    setProtos((s) => ({ ...s, [p]: { ...s[p], ...patch } }));
    if (patch.enabled === true) setExpanded((e) => ({ ...e, [p]: true }));
    if (patch.enabled === false) setExpanded((e) => ({ ...e, [p]: false }));
  };
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
        const existing = mode === "edit" ? user?.proxies?.[p] : undefined;
        if (p === "vless" || p === "vmess") {
          s.flow = v.flow;
          if (existing?.id) s.id = existing.id;
        }
        if (p === "trojan" && existing?.password) s.password = existing.password;
        if (p === "shadowsocks") {
          s.method = v.method;
          if (existing?.password) s.password = existing.password;
        }
        if (p === "wireguard" && existing) {
          if (existing.private_key) s.private_key = existing.private_key;
          if (existing.public_key) s.public_key = existing.public_key;
          if (existing.address) s.address = existing.address;
          if (existing.preshared_key) s.preshared_key = existing.preshared_key;
        }
        proxies[p] = s;
        inb[p] = v.tags;
      });
      const body: any = {
        proxies,
        inbounds: inb,
        data_limit: unlimited || !dataLimitValue ? 0 : dataLimitToBytes(dataLimitValue, dataLimitUnit),
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
    <div className="nx-drawer-overlay" onClick={onClose}>
      <div className="nx-drawer wide" onClick={(e) => e.stopPropagation()}>
        <div className="nx-drawer-head">
          <div className="nx-card-title">{mode === "create" ? t("common.create") : `${t("common.edit")} — ${user?.username}`}</div>
          <button type="button" className="nx-btn icon ghost" onClick={onClose}><IcClose /></button>
        </div>
        <div className="nx-drawer-body">
      <div className="nx-stack nx-user-form">
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
                    <div className="nx-proto-head" onClick={() => v.enabled && setExpanded((e) => ({ ...e, [p]: !e[p] }))}>
                      <div className="nx-row" style={{ gap: 10 }}>
                        <span onClick={(e) => e.stopPropagation()}>
                          <Checkbox checked={v.enabled} onChange={() => setProto(p, { enabled: !v.enabled })} />
                        </span>
                        <b>{PROTO_LABEL[p] || p}</b>
                        <span className="nx-faint" style={{ fontSize: 11 }}>{p === "wireguard" ? t("users.wgNativePeer") : `${inbounds.data?.[p]?.length || 0} inbound(s)`}</span>
                        {v.enabled && <span className="nx-faint" style={{ fontSize: 10 }}>{expanded[p] ? "▾" : "▸"}</span>}
                      </div>
                    </div>
                    {v.enabled && expanded[p] && (
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

        <div className="nx-user-form-grid">
          <Field label={t("users.dataLimit")}>
            <div className="nx-row" style={{ gap: 8 }}>
              <Input
                type="number"
                min="0"
                step={dataLimitUnit === "MB" ? "1" : "0.001"}
                value={unlimited ? "" : dataLimitValue}
                disabled={unlimited}
                placeholder="∞"
                onChange={(e: any) => setDataLimitValue(e.target.value)}
                style={{ flex: 1 }}
              />
              <Select
                value={dataLimitUnit}
                disabled={unlimited}
                onChange={(e: any) => setDataLimitUnit(e.target.value as DataLimitUnit)}
                style={{ width: 88 }}
              >
                <option value="MB">MB</option>
                <option value="GB">GB</option>
              </Select>
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
          <div style={{ gridColumn: "1 / -1" }}>
          <Field label={t("users.expire")}>
            <div className="nx-row" style={{ gap: 8, flexWrap: "wrap" }}>
              <Input type="date" value={noExpire ? "" : expireDate} disabled={noExpire} onChange={(e: any) => setExpireDate(e.target.value)} style={{ maxWidth: 200 }} />
              <label className="nx-row" style={{ gap: 6, fontSize: 12, whiteSpace: "nowrap" }}>
                <Checkbox checked={noExpire} onChange={() => setNoExpire((u) => !u)} /> {t("users.never")}
              </label>
              <div className="nx-row" style={{ gap: 4 }}>
                {[30, 60, 90].map((d) => <Button key={d} size="sm" variant="ghost" onClick={() => preset(d)}>{d}d</Button>)}
              </div>
            </div>
          </Field>
          </div>
          <Field label="Reset">
            <Select value={reset} onChange={(e: any) => setReset(e.target.value)}>
              {["no_reset", "day", "week", "month", "year"].map((r) => <option key={r} value={r}>{r}</option>)}
            </Select>
          </Field>
          <Field label={`Note (${t("common.optional")})`}><Input value={note} onChange={(e: any) => setNote(e.target.value)} /></Field>
        </div>
        <div className="nx-row" style={{ justifyContent: "flex-end", gap: 10, marginTop: 8, paddingTop: 14, borderTop: "1px solid var(--nx-border)" }}>
          <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="primary" disabled={busy || (mode === "create" && !username.trim())} onClick={submit}>
            {mode === "create" ? t("common.create") : t("common.save")}
          </Button>
        </div>
      </div>
        </div>
      </div>
    </div>
  );
};

const UserImportWizard: FC<{ onClose: () => void; onDone: () => void }> = ({ onClose, onDone }) => {
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
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  const apply = async () => {
    if (!file) return;
    if (!counts?.new) { toast.push(t("users.importNothingNew"), "error"); return; }
    if (!confirm(t("users.importApplyConfirm", { n: counts.new }))) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("skip_existing", String(skipExisting));
      fd.append("inbound_mapping", JSON.stringify(mapping));
      const res = await api.upload<{ created: number; skipped: number; errors: string[]; source?: string }>(
        "/users/import/apply-file", fd,
      );
      toast.push(t("users.importDone", { created: res.created, skipped: res.skipped }), "success");
      if (res.errors.length) toast.push(res.errors.slice(0, 5).join("; "), "error");
      onDone();
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  return (
    <Modal open title={t("users.import")} onClose={onClose} wide
      footer={<>
        <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="ghost" disabled={busy || !file} onClick={runPreview}>{t("users.importPreview")}</Button>
        <Button variant="primary" disabled={busy || !file || !counts?.new} onClick={apply}>{t("users.importApply")}</Button>
      </>}>
      <Callout tone="info" title={t("users.importWhere")}>
        <div className="nx-stack" style={{ gap: 6, fontSize: 13 }}>
          <div>{t("users.importFmtMarzban")}</div>
          <div>{t("users.importFmt3xui")}</div>
          <div>{t("users.importFmtCsv")}</div>
          <div>{t("users.importFmtLinks")}</div>
        </div>
      </Callout>
      <div style={{ marginTop: 12 }}>
        <Field label={t("users.importFile")}>
          <input
            type="file"
            accept=".json,.csv,.txt"
            onChange={(e) => { setFile(e.target.files?.[0] || null); setPreview(null); setMapping({}); }}
          />
        </Field>
      </div>
      <label className="nx-row" style={{ gap: 8, marginTop: 8, fontSize: 13 }}>
        <input type="checkbox" checked={skipExisting} onChange={(e) => setSkipExisting(e.target.checked)} />
        {t("users.importSkipExisting")}
      </label>
      {preview && (
        <div className="nx-row" style={{ gap: 10, marginTop: 10, flexWrap: "wrap", fontSize: 12 }}>
          <Pill tone="accent">{t("users.importSource")}: {preview.source || "—"}</Pill>
          <Pill>{t("users.importTotal")}: {counts?.total ?? preview.total}</Pill>
          <Pill tone="ok">{t("users.importNew")}: {counts?.new ?? 0}</Pill>
          <Pill>{t("users.importExists")}: {counts?.exists ?? 0}</Pill>
          {(counts?.invalid ?? 0) > 0 && <Pill tone="warn">{t("users.importInvalid")}: {counts?.invalid}</Pill>}
          {preview.truncated && <span className="nx-faint">{t("users.importTruncated")}</span>}
        </div>
      )}
      {unmapped.length > 0 && (
        <Callout tone="warn" title={t("users.importMapTitle")}>
          <div className="nx-stack" style={{ gap: 8, marginTop: 8 }}>
            {unmapped.map((tag) => (
              <div key={tag} className="nx-row" style={{ gap: 8, flexWrap: "wrap" }}>
                <span className="nx-code">{tag}</span>
                <span>→</span>
                <Select value={mapping[tag] || ""} onChange={(e: any) => setMapping({ ...mapping, [tag]: e.target.value })} style={{ minWidth: 160 }}>
                  <option value="">{t("users.importSkipInbound")}</option>
                  {panelTags.map((pt) => <option key={pt} value={pt}>{pt}</option>)}
                </Select>
              </div>
            ))}
          </div>
        </Callout>
      )}
      {rows.length > 0 && (
        <div className="nx-table-wrap" style={{ marginTop: 12, maxHeight: 300, overflow: "auto" }}>
          <table className="nx-table">
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
                  <td>{r.status}</td>
                  <td className="nx-faint" style={{ fontSize: 11 }}>{r.proxies ? Object.keys(r.proxies).join(", ") : "—"}</td>
                  <td className="nx-faint" style={{ fontSize: 11 }}>{r.data_limit ? formatBytes(r.data_limit) : t("users.unlimited")}</td>
                  <td className="nx-faint">{r.conflict ? t(`users.importConflict.${r.conflict}`, r.conflict) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
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
  const subUrl = absoluteUrl(data?.public_subscription_url || data?.subscription_url);
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
