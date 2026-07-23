import { FC, Fragment, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { InboundsByProtocol, NodeItem, Plan, SystemStats, UserItem, UsersResponse } from "../api/types";
import { useFetch, useLiveReload } from "../lib/useFetch";
import { formatBytes, formatDate, relativeExpiry, relativeExpiryLabel, statusTone, usagePct } from "../lib/format";
import {
  bytesToDataLimitValue, dataLimitToBytes, detectDataLimitUnit, type DataLimitUnit,
} from "../lib/data-limit";
import { PageHeader } from "../components/Shell";
import {
  Button, Callout, Card, Checkbox, CopyField, Drawer, EmptyState, Field, Input, Modal, Pill, Pager, Select,
  SkeletonRows, Toggle, UsageBar, useToast,
} from "../components/ui";
import { QR } from "../components/QR";
import { absoluteUrl } from "../lib/url";
import { resolveSubscribeBrowserUrl, resolveWgUrl } from "../../lib/subscribe-url";
import { copyToClipboard } from "../lib/clipboard";
import { IcClose, IcCopy, IcEdit, IcExternal, IcEye, IcPlus, IcRefresh, IcShare, IcTrash } from "../components/icons";
import { UserTemplatesPanel, UserTemplateRow } from "../components/UserTemplates";
import { BulkAssignModal } from "../components/BulkAssignModal";
import { BulkExtendModal, BulkResetUsageModal } from "../components/BulkUserActionModals";
import { BulkCreateUsersModal } from "../components/BulkCreateUsersModal";
import { UserImportWizard } from "../components/UserImportWizard";
import { UserProtocolChips } from "../components/UserProtocolChips";
import { useApp } from "../context/AppContext";
import { useCopilot } from "../copilot/CopilotContext";
import {
  NXPANEL_WG_KIND,
  type AssignableNativeProtocols,
  defaultProtoInboundTags,
  deriveSsMethodFromInbounds,
  generateRandomUsername,
  inboundMatchesSsMethod,
  protocolAssignable,
  toggleSsInboundTag,
  userDisplayProtocols,
  userWgStackLabels,
  wgKindForSubmit,
} from "../lib/userHelpers";
import { flattenUserInbounds, inferSourceSlug } from "../lib/userListHelpers";
import { summarizeProxyCredentials } from "../lib/userCredentials";

const PAGE_SIZES = [12, 25, 50];
const STATUSES = ["active", "disabled", "expired", "limited", "on_hold"];
const FLOWS = [
  { v: "", labelKey: "users.flowNone" },
  { v: "xtls-rprx-vision", labelKey: "" },
];

const PROTO_LABEL: Record<string, string> = {
  vless: "VLESS",
  vmess: "VMess",
  trojan: "Trojan",
  shadowsocks: "Shadowsocks",
  wireguard: "WireGuard",
  amneziawg: "AmneziaWG",
  hysteria2: "Hysteria2",
  tuic: "TUIC",
  anytls: "AnyTLS",
};

const NATIVE_PROTOCOLS = ["wireguard", "amneziawg", "hysteria2", "tuic", "anytls"] as const;

const PROTO_ORDER = ["vless", "vmess", "trojan", "shadowsocks", "wireguard", "amneziawg", "hysteria2", "tuic", "anytls"];

const PROTO_VISUAL: Record<string, { icon: string; hue: string }> = {
  vless: { icon: "VL", hue: "#2ee0c4" },
  vmess: { icon: "VM", hue: "#818cf8" },
  trojan: { icon: "TR", hue: "#f59e0b" },
  shadowsocks: { icon: "SS", hue: "#38bdf8" },
  wireguard: { icon: "WG", hue: "#94a3b8" },
  amneziawg: { icon: "AW", hue: "#22d3ee" },
  hysteria2: { icon: "H2", hue: "#f472b6" },
  tuic: { icon: "TU", hue: "#34d399" },
  anytls: { icon: "AT", hue: "#a78bfa" },
};

// Above this count a hover list is just noise, so the tile only shows the number.
const STAT_POPOVER_MAX = 200;

type UserStatItem = { key: string; label: string; value?: number; color: string; hover?: boolean; aggregate?: boolean };

const UserStatTile: FC<{ item: UserStatItem; onPick: (username: string) => void }> = ({ item, onPick }) => {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<{ usernames: string[]; total: number } | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    if (data || loading) return;
    setLoading(true);
    try {
      setData(await api.get<{ usernames: string[]; total: number }>(`/users/stat-usernames?category=${item.key}&limit=${STAT_POPOVER_MAX}`));
    } catch {
      /* hover preview is best-effort */
    } finally {
      setLoading(false);
    }
  };

  const remaining = data ? Math.max(0, data.total - data.usernames.length) : 0;

  // Popover is only useful for smaller, actionable buckets — skip it for the
  // huge aggregate tiles (total clients / active) where a list is just noise.
  if (item.hover === false) {
    return (
      <div className="nx-userstat">
        <div className="nx-userstat-label">{item.label}</div>
        <div className="nx-userstat-value" style={{ color: item.color }}>
          <span className="nx-userstat-dot" />
          <span className="nx-userstat-num">{item.value != null ? item.value.toLocaleString() : "—"}</span>
        </div>
      </div>
    );
  }

  return (
    <div
      className="nx-userstat nx-userstat--hover"
      onMouseEnter={() => { setOpen(true); void load(); }}
      onMouseLeave={() => setOpen(false)}
    >
      <div className="nx-userstat-label">{item.label}</div>
      <div className="nx-userstat-value" style={{ color: item.color }}>
        <span className="nx-userstat-dot" />
        <span className="nx-userstat-num">{item.value != null ? item.value.toLocaleString() : "—"}</span>
      </div>
      {open && (
        <div className="nx-userstat-pop" role="tooltip">
          <div className="nx-userstat-pop-head" style={{ color: item.color }}>
            <span className="nx-userstat-dot" />
            <span className="nx-userstat-pop-title">{item.label}</span>
            <span className="nx-userstat-pop-count">{data ? data.total.toLocaleString() : "…"}</span>
          </div>
          <div className="nx-userstat-pop-list">
            {loading && !data && <div className="nx-userstat-pop-empty">…</div>}
            {data && data.usernames.length === 0 && (
              <div className="nx-userstat-pop-empty">{t("users.stats.emptyList")}</div>
            )}
            {data?.usernames.map((u) => (
              <button key={u} type="button" className="nx-userstat-pop-row" onClick={() => onPick(u)} title={u}>
                {u}
              </button>
            ))}
          </div>
          {remaining > 0 && (
            <div className="nx-userstat-pop-more">{t("users.stats.andMore", { n: remaining })}</div>
          )}
        </div>
      )}
    </div>
  );
};

type HeaderMenuItem = { key: string; label: string; danger?: boolean; onClick: () => void };

const HeaderMenu: FC<{ label: string; items: HeaderMenuItem[] }> = ({ label, items }) => {
  const [open, setOpen] = useState(false);
  if (!items.length) return null;
  return (
    <div className="nx-hmenu">
      <Button variant="ghost" onClick={() => setOpen((o) => !o)}>
        {label}<span aria-hidden style={{ fontSize: 9, marginInlineStart: 6, opacity: 0.7 }}>▼</span>
      </Button>
      {open && (
        <>
          <div className="nx-hmenu-backdrop" onClick={() => setOpen(false)} />
          <div className="nx-hmenu-pop" role="menu">
            {items.map((it) => (
              <button
                key={it.key}
                type="button"
                role="menuitem"
                className={`nx-hmenu-item${it.danger ? " danger" : ""}`}
                onClick={() => { setOpen(false); it.onClick(); }}
              >
                {it.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
};

export const Users: FC = () => {
  const { t, i18n } = useTranslation();
  const { admin } = useApp();
  // Support role has users:read only — hide write actions that would 403.
  const canWrite = !!admin?.is_sudo || admin?.role !== "support";
  const { consumeIntent } = useCopilot();
  const toast = useToast();
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(PAGE_SIZES[0]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [protocolFilter, setProtocolFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [inboundFilter, setInboundFilter] = useState("");
  const [expiringSoon, setExpiringSoon] = useState(false);
  const [nearLimit, setNearLimit] = useState(false);
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [createWg, setCreateWg] = useState(false);
  const [editUser, setEditUser] = useState<UserItem | null>(null);
  const [viewUser, setViewUser] = useState<UserItem | null>(null);
  const [showImport, setShowImport] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  useEffect(() => {
    if (searchParams.get("import") === "1") {
      setShowImport(true);
      const next = new URLSearchParams(searchParams);
      next.delete("import");
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, setSearchParams]);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [showBulkAssign, setShowBulkAssign] = useState(false);
  const [showBulkExtend, setShowBulkExtend] = useState(false);
  const [showBulkReset, setShowBulkReset] = useState(false);
  const [showBulkCreate, setShowBulkCreate] = useState(false);

  interface UserFilterOptions {
    source_servers: Array<{ slug: string; user_count: number }>;
    inbound_tags: string[];
    protocols: string[];
  }
  const filterOptions = useFetch<UserFilterOptions>(() => api.get("/users/filter-options"), []);

  const templates = useFetch<UserTemplateRow[]>(() => api.get("/user_template"), []);
  const inboundsList = useFetch<InboundsByProtocol>(() => api.get("/inbounds"), []);
  const nodesForBulk = useFetch<NodeItem[]>(() => api.get("/nodes"), []);
  const nativeCapsForBulk = useFetch<AssignableNativeProtocols>(
    () => api.get("/assignable-native-protocols"),
    [],
  );
  const inboundTags = useMemo(() => {
    const ib = inboundsList.data;
    if (!ib) return [] as string[];
    const tags = new Set<string>();
    Object.values(ib).forEach((rows) => rows?.forEach((r) => tags.add(r.tag)));
    return Array.from(tags).sort();
  }, [inboundsList.data]);

  const toggleSelected = (username: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(username)) next.delete(username);
      else next.add(username);
      return next;
    });
  };
  const selectAllOnPage = () => {
    if (!data?.users.length) return;
    setSelected(new Set(data.users.map((u) => u.username)));
  };
  const clearSelection = () => setSelected(new Set());

  // The Copilot can deep-link straight into "create user" (optionally WireGuard).
  useEffect(() => {
    if (consumeIntent("create-wg-user")) { setCreateWg(true); setShowCreate(true); }
    else if (consumeIntent("create-user")) { setCreateWg(false); setShowCreate(true); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const query = useMemo(() => {
    const p = new URLSearchParams();
    p.set("offset", String(page * pageSize));
    p.set("limit", String(pageSize));
    if (search.trim()) p.set("search", search.trim());
    if (statusFilter) p.set("status", statusFilter);
    if (protocolFilter) p.set("protocol", protocolFilter);
    if (sourceFilter) p.set("source_slug", sourceFilter);
    if (inboundFilter) p.set("inbound_tag", inboundFilter);
    if (expiringSoon) p.set("expiring_within_days", "7");
    if (nearLimit) p.set("near_limit_percent", "85");
    p.set("sort", "created_at");
    return p.toString();
  }, [page, pageSize, search, statusFilter, protocolFilter, sourceFilter, inboundFilter, expiringSoon, nearLimit]);

  const activeFilterCount = useMemo(() => {
    let n = 0;
    if (protocolFilter) n += 1;
    if (sourceFilter) n += 1;
    if (inboundFilter) n += 1;
    if (expiringSoon) n += 1;
    if (nearLimit) n += 1;
    return n;
  }, [protocolFilter, sourceFilter, inboundFilter, expiringSoon, nearLimit]);

  const knownSourceSlugs = useMemo(
    () => (filterOptions.data?.source_servers || []).map((s) => s.slug),
    [filterOptions.data],
  );

  const clearAdvancedFilters = () => {
    setProtocolFilter("");
    setSourceFilter("");
    setInboundFilter("");
    setExpiringSoon(false);
    setNearLimit(false);
    setPage(0);
  };

  const { data, loading, error, reload } = useFetch<UsersResponse>(() => api.get(`/users?${query}`), [query]);
  useLiveReload(reload, 30000);
  const sys = useFetch<SystemStats>(() => api.get("/system"), []);
  useLiveReload(sys.reload, 30000);
  const st = sys.data;
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / pageSize));

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

  const bulkStatus = async (action: "enable" | "disable") => {
    if (!confirm(t(`users.bulk.${action}Confirm`, { n: selected.size }))) return;
    try {
      const r = await api.post<{ applied: number; skipped: number; failed: number }>("/users/bulk/status", {
        scope: "selected", usernames: Array.from(selected), action,
      });
      toast.push(t("users.bulk.statusDone", { applied: r.applied, skipped: r.skipped }), r.failed ? "error" : "success");
      clearSelection(); reload();
    } catch (e: any) { toast.push(e.message, "error"); }
  };

  const bulkDelete = async (opts: { scope: "selected" | "all" | "filtered"; statuses?: string[]; confirmKey: string; count: number }) => {
    if (!confirm(t(opts.confirmKey, { n: opts.count }))) return;
    if (opts.scope === "all" && !confirm(t("users.bulk.deleteAllConfirm2"))) return;
    try {
      const started = await api.post<{
        deleted?: number;
        job_id?: string;
        async?: boolean;
        total?: number;
      }>("/users/bulk/delete", {
        scope: opts.scope,
        usernames: opts.scope === "selected" ? Array.from(selected) : [],
        statuses: opts.statuses || [],
      });
      let deleted = started.deleted ?? 0;
      if (started.job_id) {
        toast.push(t("users.bulk.deleteStarted", { n: started.total ?? opts.count }), "info");
        for (;;) {
          const s = await api.get<{
            state: string;
            processed: number;
            total: number;
            deleted: number;
            error?: string | null;
          }>(`/users/bulk/delete/status/${started.job_id}`);
          if (s.state === "done") {
            deleted = s.deleted;
            break;
          }
          if (s.state === "error") {
            throw new Error(s.error || t("common.error"));
          }
          await new Promise((r) => setTimeout(r, 1500));
        }
      }
      toast.push(t("users.bulk.deleteDone", { n: deleted }), "success");
      clearSelection(); reload();
    } catch (e: any) { toast.push(e.message, "error"); }
  };

  return (
    <div className="nx-page">
      <PageHeader
        title={t("users.title")}
        subtitle={t("users.subtitle")}
        description={t("users.description")}
        actions={<>
          <Button variant="ghost" title={t("common.refresh")} onClick={reload}><IcRefresh className="nx-ico" /></Button>
          <HeaderMenu
            label={t("users.cleanup")}
            items={[
              ...(admin?.is_sudo ? [{
                key: "reset",
                label: t("users.resetAllUsage"),
                onClick: async () => {
                  if (!confirm(t("users.resetAllUsageConfirm"))) return;
                  try {
                    await api.post("/users/reset");
                    toast.push(t("users.resetAllUsageDone"), "success");
                    reload();
                  } catch (e: any) {
                    toast.push(e.message, "error");
                  }
                },
              }] : []),
              ...(canWrite ? [
                {
                  key: "delInactive",
                  label: t("users.bulk.deleteInactive"),
                  danger: true,
                  onClick: () => bulkDelete({ scope: "filtered", statuses: ["disabled", "expired"], confirmKey: "users.bulk.deleteInactiveConfirm", count: (st?.users_disabled ?? 0) + (st?.users_expired ?? 0) }),
                },
                {
                  key: "delAll",
                  label: t("users.bulk.deleteAll"),
                  danger: true,
                  onClick: () => bulkDelete({ scope: "all", confirmKey: "users.bulk.deleteAllConfirm", count: total }),
                },
              ] : []),
            ]}
          />
          {canWrite && <Button variant="ghost" onClick={() => setShowImport(true)}>{t("users.import")}</Button>}
          {canWrite && (
            <Button variant="ghost" onClick={() => setShowBulkCreate(true)}>
              {t("bulkCreate.short")}
            </Button>
          )}
          {canWrite && (
            <Button variant="ghost" onClick={() => setShowBulkAssign(true)}>
              {t("bulkAssign.short")}
            </Button>
          )}
          {canWrite && <Button variant="primary" onClick={() => setShowCreate(true)}><IcPlus className="nx-ico" /> {t("common.create")}</Button>}
        </>}
      />

      <Card className="nx-glass-card nx-userstats nx-mb-20">
        {([
          { key: "total", label: t("users.stats.total"), value: st?.total_user, color: "var(--nx-accent)", aggregate: true },
          { key: "online", label: t("users.stats.online"), value: st?.online_users, color: "var(--nx-info)" },
          { key: "expired", label: t("users.status.expired"), value: st?.users_expired, color: "#a78bfa" },
          { key: "limited", label: t("users.status.limited"), value: st?.users_limited, color: "var(--nx-warn)" },
          { key: "on_hold", label: t("users.status.on_hold"), value: st?.users_on_hold, color: "#22d3ee" },
          { key: "disabled", label: t("users.status.disabled"), value: st?.users_disabled, color: "var(--nx-text-dim)" },
          { key: "active", label: t("users.status.active"), value: st?.users_active, color: "var(--nx-ok)", aggregate: true },
        ] as UserStatItem[]).map((it) => (
          <UserStatTile
            key={it.key}
            // Preview list only for small, actionable buckets — aggregates
            // (total/active) and large sets just show the number to stay clean.
            item={{ ...it, hover: !it.aggregate && it.value != null && it.value > 0 && it.value <= STAT_POPOVER_MAX }}
            onPick={(u) => { setSearch(u); setPage(0); }}
          />
        ))}
      </Card>

      {admin?.is_sudo && <UserTemplatesPanel />}

      <Card className="nx-toolbar nx-mb-20">
        <div className="nx-toolbar-inner" style={{ flexWrap: "wrap", gap: 10 }}>
          <Input
            placeholder={t("users.searchPlaceholder")}
            value={search}
            onChange={(e: any) => { setSearch(e.target.value); setPage(0); }}
            style={{ maxWidth: 280, minWidth: 180 }}
          />
          <Select value={statusFilter} onChange={(e: any) => { setStatusFilter(e.target.value); setPage(0); }} style={{ maxWidth: 180 }}>
            <option value="">{t("common.all")} — {t("common.status")}</option>
            {STATUSES.map((s) => <option key={s} value={s}>{t(`users.status.${s}`)}</option>)}
          </Select>
          <Button
            size="sm"
            variant={showAdvancedFilters || activeFilterCount > 0 ? "primary" : "ghost"}
            onClick={() => setShowAdvancedFilters((v) => !v)}
          >
            {t("users.filters.advanced")}
            {activeFilterCount > 0 ? ` (${activeFilterCount})` : ""}
          </Button>
          {activeFilterCount > 0 && (
            <Button size="sm" variant="ghost" onClick={clearAdvancedFilters}>{t("users.filters.clear")}</Button>
          )}
          <div className="nx-spacer" />
          <Select
            value={String(pageSize)}
            onChange={(e: any) => { setPageSize(parseInt(e.target.value, 10)); setPage(0); }}
            style={{ maxWidth: 100 }}
            title={t("users.perPage")}
          >
            {PAGE_SIZES.map((n) => <option key={n} value={n}>{n} {t("users.perPage")}</option>)}
          </Select>
          <span className="nx-faint" style={{ fontSize: 12 }}>{t("common.total")}: {total}</span>
        </div>
        {(showAdvancedFilters || activeFilterCount > 0) && (
          <div className="nx-toolbar-inner" style={{ flexWrap: "wrap", gap: 10, marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--nx-border, rgba(255,255,255,.08))" }}>
            <Select value={protocolFilter} onChange={(e: any) => { setProtocolFilter(e.target.value); setPage(0); }} style={{ maxWidth: 180 }}>
              <option value="">{t("users.filters.allProtocols")}</option>
              {(filterOptions.data?.protocols || PROTO_ORDER).map((p) => (
                <option key={p} value={p}>{PROTO_LABEL[p] || p}</option>
              ))}
            </Select>
            <Select value={sourceFilter} onChange={(e: any) => { setSourceFilter(e.target.value); setPage(0); }} style={{ maxWidth: 200 }}>
              <option value="">{t("users.filters.allSources")}</option>
              {(filterOptions.data?.source_servers || []).map((s) => (
                <option key={s.slug} value={s.slug}>{s.slug} ({s.user_count})</option>
              ))}
            </Select>
            <Select value={inboundFilter} onChange={(e: any) => { setInboundFilter(e.target.value); setPage(0); }} style={{ maxWidth: 220 }}>
              <option value="">{t("users.filters.allInbounds")}</option>
              {(filterOptions.data?.inbound_tags || inboundTags).map((tag) => (
                <option key={tag} value={tag}>{tag}</option>
              ))}
            </Select>
            <label className="nx-row" style={{ gap: 6, fontSize: 12 }}>
              <Checkbox checked={expiringSoon} onChange={() => { setExpiringSoon((v) => !v); setPage(0); }} />
              {t("users.filters.expiringSoon")}
            </label>
            <label className="nx-row" style={{ gap: 6, fontSize: 12 }}>
              <Checkbox checked={nearLimit} onChange={() => { setNearLimit((v) => !v); setPage(0); }} />
              {t("users.filters.nearLimit")}
            </label>
          </div>
        )}
      </Card>

      {canWrite && selected.size > 0 && (
        <Card className="nx-mb-20" style={{ padding: "12px 16px" }}>
          <div className="nx-row" style={{ flexWrap: "wrap", gap: 10 }}>
            <span style={{ fontWeight: 600 }}>{t("bulkInbound.selectedCount", { n: selected.size })}</span>
            <Button size="sm" variant="primary" onClick={() => setShowBulkExtend(true)}>{t("bulkExtend.short")}</Button>
            <Button size="sm" variant="ghost" onClick={() => setShowBulkAssign(true)}>{t("bulkAssign.short")}</Button>
            <Button size="sm" variant="ghost" onClick={() => setShowBulkReset(true)}>{t("bulkReset.short")}</Button>
            <Button size="sm" variant="ghost" onClick={() => bulkStatus("enable")}>{t("users.bulk.enable")}</Button>
            <Button size="sm" variant="ghost" onClick={() => bulkStatus("disable")}>{t("users.bulk.disable")}</Button>
            <Button size="sm" variant="danger" onClick={() => bulkDelete({ scope: "selected", confirmKey: "users.bulk.deleteSelectedConfirm", count: selected.size })}>{t("users.bulk.delete")}</Button>
            <Button size="sm" variant="ghost" onClick={clearSelection}>{t("bulkInbound.clearSelection")}</Button>
          </div>
        </Card>
      )}

      <Card pad0>
        {loading && !data ? <div style={{ padding: 20 }}><SkeletonRows rows={6} cols={5} /></div>
          : error && !data ? <EmptyState title={t("common.error")} desc={error} action={<Button onClick={() => reload({ background: false })}>{t("common.retry")}</Button>} />
          : !data?.users.length ? <EmptyState title={t("common.noData")} action={<Button variant="primary" onClick={() => setShowCreate(true)}><IcPlus className="nx-ico" /> {t("common.create")}</Button>} />
          : (
            <div className="nx-table-wrap">
              <table className="nx-table">
                <thead><tr>
                  {canWrite && (
                    <th style={{ width: 40 }}>
                      <Checkbox
                        checked={!!data?.users.length && data.users.every((u) => selected.has(u.username))}
                        onChange={() => {
                          if (data?.users.every((u) => selected.has(u.username))) clearSelection();
                          else selectAllOnPage();
                        }}
                      />
                    </th>
                  )}
                  <th>{t("common.username")}</th><th>{t("common.status")}</th>
                  <th className="nx-col-inbound">{t("users.filters.serverInbound")}</th>
                  <th className="nx-col-proto" style={{ width: 156 }}>{t("common.protocols")}</th>
                  <th>{t("users.used")}</th><th className="nx-col-expire">{t("users.expire")}</th><th style={{ textAlign: "end" }}>{t("common.actions")}</th>
                </tr></thead>
                <tbody>
                  {data.users.map((u) => {
                    const pct = usagePct(u.used_traffic, u.data_limit);
                    const protos = userDisplayProtocols(u.proxies as Record<string, unknown> | undefined);
                    const inboundTagsList = flattenUserInbounds(u.inbounds);
                    const sourceSlug = inferSourceSlug(u.username, knownSourceSlugs);
                    return (
                      <tr key={u.username} style={{ cursor: "pointer" }} onClick={() => setViewUser(u)}>
                        {canWrite && (
                          <td onClick={(e) => e.stopPropagation()}>
                            <Checkbox
                              checked={selected.has(u.username)}
                              onChange={() => toggleSelected(u.username)}
                            />
                          </td>
                        )}
                        <td style={{ fontWeight: 600 }}>{u.username}{u.note ? <div className="nx-faint" style={{ fontWeight: 400, fontSize: 11 }}>{u.note}</div> : null}</td>
                        <td>
                          {u.online ? (
                            <span className="nx-online-badge" title={t(`users.status.${u.status}`, u.status)}>
                              <span className="nx-online-dot" />
                              {t("users.stats.online")}
                            </span>
                          ) : (
                            <Pill tone={statusTone(u.status)} dot>{t(`users.status.${u.status}`, u.status)}</Pill>
                          )}
                        </td>
                        <td className="nx-col-inbound" style={{ maxWidth: 200 }}>
                          {sourceSlug ? (
                            <Pill tone="default">{sourceSlug}</Pill>
                          ) : (
                            <span className="nx-faint">—</span>
                          )}
                          {inboundTagsList.length > 0 ? (
                            <div className="nx-faint" style={{ fontSize: 11, marginTop: 4, lineHeight: 1.35 }} title={inboundTagsList.join(", ")}>
                              {inboundTagsList.slice(0, 2).join(", ")}
                              {inboundTagsList.length > 2 ? ` +${inboundTagsList.length - 2}` : ""}
                            </div>
                          ) : null}
                        </td>
                        <td className="nx-col-proto"><UserProtocolChips protos={protos} /></td>
                        <td className="nx-col-used" style={{ minWidth: 170 }}>
                          <div style={{ fontSize: 12 }}>{formatBytes(u.used_traffic)} / {u.data_limit ? formatBytes(u.data_limit) : t("users.unlimited")}</div>
                          {(u.overage_traffic ?? 0) > 0 ? (
                            <div className="nx-faint" style={{ fontSize: 11, marginTop: 2, color: "var(--nx-danger, #ef4444)" }}>
                              +{formatBytes(u.overage_traffic!)} {t("users.overage")}
                            </div>
                          ) : null}
                          {u.data_limit ? <div style={{ marginTop: 5 }}><UsageBar pct={pct} /></div> : null}
                        </td>
                        <td className="nx-col-expire">{u.expire ? formatDate(u.expire, i18n.language) : <span className="nx-faint">{t("users.never")}</span>}</td>
                        <td onClick={(e) => e.stopPropagation()}>
                          <div className="nx-row" style={{ justifyContent: "flex-end", gap: 6, flexWrap: "nowrap" }}>
                            <Button className="nx-col-view-btn" size="sm" variant="ghost" title={t("common.view")} onClick={() => setViewUser(u)}><IcEye className="nx-ico" /></Button>
                            {canWrite && <Button size="sm" variant="ghost" title={t("common.edit")} onClick={() => setEditUser(u)}><IcEdit className="nx-ico" /></Button>}
                            {canWrite && <Toggle on={u.status !== "disabled"} onChange={() => toggleUser(u)} label={t("users.toggleStatus")} />}
                            {canWrite && <Button variant="danger" size="sm" title={t("common.delete")} onClick={() => removeUser(u)}><IcTrash className="nx-ico" /></Button>}
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

      {total > pageSize && (
        <Pager
          page={page}
          pages={pages}
          onPage={setPage}
          summary={t("users.showing", {
            from: page * pageSize + 1,
            to: Math.min((page + 1) * pageSize, total),
            total,
          })}
        />
      )}

      {showCreate && <UserFormDrawer mode="create" presetWireguard={createWg} onClose={() => setShowCreate(false)} onDone={() => { setShowCreate(false); reload(); }} />}
      {editUser && <UserFormDrawer mode="edit" user={editUser} onClose={() => setEditUser(null)} onDone={() => { setEditUser(null); reload(); }} />}
      {showImport && <UserImportWizard onClose={() => setShowImport(false)} onDone={() => { setShowImport(false); reload(); }} />}
      {viewUser && <UserDetail username={viewUser.username} onClose={() => setViewUser(null)} onEdit={() => { setEditUser(viewUser); setViewUser(null); }} />}
      {showBulkAssign && (
        <BulkAssignModal
          open
          onClose={() => setShowBulkAssign(false)}
          onDone={() => { clearSelection(); reload(); }}
          selectedUsernames={Array.from(selected)}
          totalUsers={total}
          inboundTags={inboundTags}
          inbounds={inboundsList.data ?? undefined}
          nodes={nodesForBulk.data ?? undefined}
          nativeCaps={nativeCapsForBulk.data}
        />
      )}
      {showBulkExtend && (
        <BulkExtendModal
          open
          onClose={() => setShowBulkExtend(false)}
          onDone={() => { clearSelection(); reload(); }}
          selectedUsernames={Array.from(selected)}
        />
      )}
      {showBulkReset && (
        <BulkResetUsageModal
          open
          onClose={() => setShowBulkReset(false)}
          onDone={() => { clearSelection(); reload(); }}
          selectedUsernames={Array.from(selected)}
        />
      )}
      {showBulkCreate && (
        <BulkCreateUsersModal
          open
          onClose={() => setShowBulkCreate(false)}
          onDone={() => reload()}
          templates={templates.data || []}
        />
      )}
    </div>
  );
};

/* --------------------------- shared user form --------------------------- */
type ProtoState = { enabled: boolean; tags: string[]; flow: string; method: string };

const WIZARD_STEPS = ["wizardStep1", "wizardStep2", "wizardStep3"] as const;

type UserFormTab = "protocols" | "plan" | "advanced";

const UserFormDrawer: FC<{ mode: "create" | "edit"; user?: UserItem; presetWireguard?: boolean; onClose: () => void; onDone: () => void }> = ({ mode, user, presetWireguard, onClose, onDone }) => {
  const { t } = useTranslation();
  const { admin, isEnabled, expertMode } = useApp();
  const canWrite = !!admin?.is_sudo || admin?.role !== "support";
  const toast = useToast();
  const inbounds = useFetch<InboundsByProtocol>(() => api.get("/inbounds"), []);
  const nodes = useFetch<NodeItem[]>(() => api.get("/nodes"), []);
  const nativeCaps = useFetch<AssignableNativeProtocols>(
    () => api.get("/assignable-native-protocols"),
    [],
  );
  useEffect(() => {
    inbounds.reload();
    nodes.reload();
    nativeCaps.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const hasHy2Node = nativeCaps.data?.hysteria2
    ?? (nodes.data || []).some((n) => n.singbox?.hysteria2_enabled);
  const hasTuicNode = nativeCaps.data?.tuic
    ?? (nodes.data || []).some((n) => n.singbox?.tuic_enabled);
  const hasAnytlsNode = nativeCaps.data?.anytls
    ?? (nodes.data || []).some((n) => n.singbox?.anytls_enabled);
  const hasPlainWgNode = nativeCaps.data?.wireguard
    ?? (nodes.data || []).some((n) => {
      const wg = n.wireguard;
      if (!wg) return false;
      if (wg.xray_wg_enabled) return true;
      if (wg.plain_enabled === false) return false;
      return n.core_kind === "wireguard";
    });
  const hasAwgNode = nativeCaps.data?.amneziawg
    ?? (nodes.data || []).some(
      (n) => n.core_kind === "wireguard" && !!n.wireguard?.awg_enabled,
    );
  const templates = useFetch<{ id: number; name?: string }[]>(
    () => (admin?.is_sudo ? api.get("/user_template") : Promise.resolve([])),
    [admin?.is_sudo],
  );
  const routingPresets = useFetch<{ presets: Record<string, { label: string }> }>(
    () => api.get("/routing/presets"),
    [],
  );
  const dnsPresets = useFetch<{ presets: Record<string, { label: string }> }>(
    () => api.get("/routing/dns-presets"),
    [],
  );
  const [templateId, setTemplateId] = useState("");

  const [username, setUsername] = useState(
    user?.username || (mode === "create" ? generateRandomUsername() : ""),
  );
  const [dataLimitUnit, setDataLimitUnit] = useState<DataLimitUnit>(
    user?.data_limit ? detectDataLimitUnit(user.data_limit) : "GB",
  );
  const [dataLimitValue, setDataLimitValue] = useState(
    user?.data_limit ? bytesToDataLimitValue(user.data_limit, detectDataLimitUnit(user.data_limit)) : "",
  );
  const [expireDate, setExpireDate] = useState(user?.expire ? new Date(user.expire * 1000).toISOString().slice(0, 10) : "");
  const [noExpire, setNoExpire] = useState(!user?.expire);
  const [status, setStatus] = useState(
    user && ["active", "on_hold", "disabled", "limited", "expired"].includes(user.status) ? user.status : "active"
  );
  const [reset, setReset] = useState(user?.data_limit_reset_strategy || "no_reset");
  const [clientProfile, setClientProfile] = useState(user?.client_profile || "normal");
  const [routingPreset, setRoutingPreset] = useState(user?.routing_preset || "");
  const [dnsPreset, setDnsPreset] = useState(
    (user?.dns_policy && typeof user.dns_policy === "object" && "preset" in user.dns_policy
      ? String((user.dns_policy as { preset?: string }).preset || "")
      : "") || "",
  );
  const [speedUp, setSpeedUp] = useState(
    user?.speed_limit_up != null ? String(user.speed_limit_up) : "",
  );
  const [speedDown, setSpeedDown] = useState(
    user?.speed_limit_down != null ? String(user.speed_limit_down) : "",
  );
  const [deviceLimit, setDeviceLimit] = useState(
    user?.device_limit != null ? String(user.device_limit) : "",
  );
  const [sessionLimitMinutes, setSessionLimitMinutes] = useState(
    user?.session_limit_minutes != null ? String(user.session_limit_minutes) : "",
  );
  const [note, setNote] = useState(user?.note || "");
  const [portalEnabled, setPortalEnabled] = useState(!!user?.portal_enabled);
  const [portalPassword, setPortalPassword] = useState("");
  const [protos, setProtos] = useState<Record<string, ProtoState>>({});
  const [busy, setBusy] = useState(false);
  const [loadingEdit, setLoadingEdit] = useState(mode === "edit");
  const [fetchedUser, setFetchedUser] = useState<UserItem | null>(null);
  const [subToken, setSubToken] = useState("");
  const [subscriptionUrl, setSubscriptionUrl] = useState("");
  const [subRevokedAt, setSubRevokedAt] = useState<string | null>(null);
  const [credBusy, setCredBusy] = useState(false);
  const [formTab, setFormTab] = useState<UserFormTab>(mode === "edit" ? "plan" : "protocols");
  const [wizardStep, setWizardStep] = useState(1);
  const useWizard = mode === "create" && !expertMode && !templateId;
  const tabbedForm = !useWizard;
  const editProfile = mode === "edit" ? (fetchedUser ?? user) : user;

  const applyCredentialRefresh = (record: UserItem) => {
    setFetchedUser(record);
    hydrateFromUser(record);
    setSubToken(record.sub_token || "");
    setSubscriptionUrl(record.subscription_url || record.public_subscription_url || "");
    setSubRevokedAt(record.sub_revoked_at || null);
  };

  const hydrateFromUser = (record: UserItem) => {
    setDataLimitUnit(record.data_limit ? detectDataLimitUnit(record.data_limit) : "GB");
    setDataLimitValue(
      record.data_limit
        ? bytesToDataLimitValue(record.data_limit, detectDataLimitUnit(record.data_limit))
        : "",
    );
    setExpireDate(record.expire ? new Date(record.expire * 1000).toISOString().slice(0, 10) : "");
    setNoExpire(!record.expire);
    setStatus(
      ["active", "on_hold", "disabled", "limited", "expired"].includes(record.status)
        ? record.status
        : "active",
    );
    setReset(record.data_limit_reset_strategy || "no_reset");
    setClientProfile(record.client_profile || "normal");
    setRoutingPreset(record.routing_preset || "");
    setDnsPreset(
      record.dns_policy && typeof record.dns_policy === "object" && "preset" in record.dns_policy
        ? String((record.dns_policy as { preset?: string }).preset || "")
        : "",
    );
    setSpeedUp(record.speed_limit_up != null ? String(record.speed_limit_up) : "");
    setSpeedDown(record.speed_limit_down != null ? String(record.speed_limit_down) : "");
    setDeviceLimit(record.device_limit != null ? String(record.device_limit) : "");
    setSessionLimitMinutes(
      record.session_limit_minutes != null ? String(record.session_limit_minutes) : "",
    );
    setNote(record.note || "");
    setPortalEnabled(!!record.portal_enabled);
    setPortalPassword("");
  };

  useEffect(() => {
    if (mode !== "edit" || !user?.username) {
      setLoadingEdit(false);
      return;
    }
    let cancelled = false;
    setLoadingEdit(true);
    api.get<UserItem>(`/user/${encodeURIComponent(user.username)}`)
      .then((full) => {
        if (cancelled) return;
        applyCredentialRefresh(full);
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          toast.push(e instanceof Error ? e.message : t("common.error"), "error");
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingEdit(false);
      });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, user?.username]);

  // Initialize protocol state once inbounds + user are known.
  useEffect(() => {
    if (!inbounds.data) return;
    const profile = mode === "edit" ? (fetchedUser ?? user) : user;
    const awgInboundTags = (inbounds.data.amneziawg || []).map((i) => i.tag);
    const next: Record<string, ProtoState> = {};
    const userProtos = profile?.proxies ? Object.keys(profile.proxies) : [];
    Object.keys(inbounds.data).forEach((proto) => {
      if (proto === "amneziawg") return;
      const tags = inbounds.data![proto].map((i) => i.tag);
      const enabled = mode === "edit" ? userProtos.includes(proto) : false;
      const selected = profile?.inbounds?.[proto] || tags;
      next[proto] = {
        enabled,
        tags: enabled ? selected.filter((s) => tags.includes(s)) : tags,
        flow: profile?.proxies?.[proto]?.flow || "",
        method: profile?.proxies?.[proto]?.method || "chacha20-ietf-poly1305",
      };
    });
    // WireGuard is a first-class protocol that is *not* an Xray inbound, so it
    // never comes back from /inbounds. Surface it as a synthetic toggle: the
    // server generates the peer keypair + allocates the IP automatically.
    const wgSettings = profile?.proxies?.wireguard as {
      awg_address?: string;
      address?: string;
      nexusPanelKind?: string;
    } | undefined;
    const wgKind = wgSettings?.nexusPanelKind;
    const hasAwgPeer = !!(wgSettings?.awg_address);
    const hasPlainPeer = !!(wgSettings?.address);
    next["amneziawg"] = {
      enabled: mode === "edit" ? userProtos.includes("wireguard") && (wgKind === "amneziawg" || wgKind === "both" || (hasAwgPeer && !hasPlainPeer && !wgKind)) : false,
      tags: mode === "edit"
        ? (profile?.inbounds?.wireguard || []).filter((t) => awgInboundTags.includes(t))
        : awgInboundTags,
      flow: "",
      method: "",
    };
    next["wireguard"] = {
      enabled: mode === "edit" ? userProtos.includes("wireguard") && (wgKind === "wireguard" || wgKind === "both" || (hasPlainPeer && !hasAwgPeer && !wgKind) || (!hasPlainPeer && !hasAwgPeer && !wgKind)) : !!presetWireguard,
      tags: [],
      flow: "",
      method: "",
    };
    if (mode === "edit" && userProtos.includes("wireguard") && wgKind === "amneziawg") {
      next["wireguard"].enabled = false;
      next["amneziawg"].enabled = true;
    } else if (mode === "edit" && userProtos.includes("wireguard") && wgKind === "both") {
      next["wireguard"].enabled = true;
      next["amneziawg"].enabled = true;
    } else if (mode === "edit" && userProtos.includes("wireguard") && wgKind === "wireguard") {
      next["wireguard"].enabled = true;
      next["amneziawg"].enabled = false;
    } else if (mode === "edit" && userProtos.includes("wireguard") && hasPlainPeer && !hasAwgPeer) {
      next["wireguard"].enabled = true;
      next["amneziawg"].enabled = false;
    } else if (mode === "edit" && userProtos.includes("wireguard") && hasAwgPeer && !hasPlainPeer) {
      next["wireguard"].enabled = false;
      next["amneziawg"].enabled = true;
    }
    for (const p of ["hysteria2", "tuic", "anytls"]) {
      next[p] = {
        enabled: mode === "edit" ? userProtos.includes(p) : false,
        tags: [],
        flow: "",
        method: "",
      };
    }
    setProtos(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inbounds.data, mode, fetchedUser, user?.username, presetWireguard]);

  const credentialLines = useMemo(
    () => summarizeProxyCredentials(editProfile?.proxies),
    [editProfile?.proxies],
  );

  const handleRevokeSub = async () => {
    if (!user?.username || credBusy) return;
    if (!confirm(t("users.revokeSubFullConfirm"))) return;
    setCredBusy(true);
    try {
      const full = await api.post<UserItem>(`/user/${encodeURIComponent(user.username)}/revoke_sub`);
      applyCredentialRefresh(full);
      toast.push(t("users.revokeSubDone"), "success");
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
    } finally {
      setCredBusy(false);
    }
  };

  const handleRotateSub = async () => {
    if (!user?.username || credBusy) return;
    if (!confirm(t("users.rotateSubLinkConfirm"))) return;
    setCredBusy(true);
    try {
      const full = await api.post<UserItem>(`/user/${encodeURIComponent(user.username)}/rotate_sub`);
      applyCredentialRefresh(full);
      toast.push(t("common.saved"), "success");
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
    } finally {
      setCredBusy(false);
    }
  };

  const setProto = (p: string, patch: Partial<ProtoState>) => {
    setProtos((s) => ({ ...s, [p]: { ...s[p], ...patch } }));
  };
  const toggleTag = (p: string, tag: string) => setProtos((s) => {
    const cur = s[p];
    const ibList = p === "amneziawg"
      ? (inbounds.data?.amneziawg || [])
      : (inbounds.data?.[p] || []);
    const tags = p === "shadowsocks"
      ? toggleSsInboundTag(cur.tags, tag, ibList)
      : (cur.tags.includes(tag) ? cur.tags.filter((x) => x !== tag) : [...cur.tags, tag]);
    return { ...s, [p]: { ...cur, tags } };
  });

  const enabledProtos = Object.entries(protos).filter(([, v]) => v.enabled);
  const wgStackEnabled = !!(protos.wireguard?.enabled || protos.amneziawg?.enabled);

  const submitEnabledProtos = (): [string, ProtoState][] => {
    const rows = enabledProtos.filter(([p]) => p !== "amneziawg");
    if (wgStackEnabled && !rows.some(([p]) => p === "wireguard")) {
      rows.push(["wireguard", protos.wireguard || { enabled: true, tags: [], flow: "", method: "" }]);
    }
    return rows;
  };

  const submit = async () => {
    if (mode === "create" && templateId) {
      if (!username.trim()) { toast.push(t("users.usernameRequired"), "error"); return; }
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
    if (!enabledProtos.length) { toast.push(t("users.selectProtocol"), "error"); return; }
    const awgInboundTags = inbounds.data?.amneziawg?.map((i) => i.tag) || [];
    if (protos.amneziawg?.enabled && awgInboundTags.length > 0 && !protos.amneziawg.tags?.length) {
      toast.push(t("users.inboundRequired", { proto: PROTO_LABEL.amneziawg }), "error");
      return;
    }
    const apiProtos = submitEnabledProtos();
    for (const [p, v] of apiProtos) {
      if (!NATIVE_PROTOCOLS.includes(p as typeof NATIVE_PROTOCOLS[number]) && !v.tags.length) {
        toast.push(t("users.inboundRequired", { proto: PROTO_LABEL[p] || p }), "error");
        return;
      }
    }
    if (isEnabled("user_portal") && portalEnabled && mode === "create" && !portalPassword.trim()) {
      toast.push(t("users.portalPassword"), "error");
      return;
    }
    setBusy(true);
    try {
      const proxies: Record<string, any> = {};
      const inb: Record<string, string[]> = {};
      apiProtos.forEach(([p, v]) => {
        const s: any = {};
        const existing = mode === "edit" ? editProfile?.proxies?.[p] : undefined;
        if (p === "vless" || p === "vmess" || p === "trojan") {
          if (v.flow) s.flow = v.flow;
          if (p === "vless" || p === "vmess") {
            if (existing?.id) s.id = existing.id;
          }
        }
        if (p === "trojan" && existing?.password) s.password = existing.password;
        if (p === "shadowsocks") {
          const method = deriveSsMethodFromInbounds(v.tags, inbounds.data?.shadowsocks || [])
            || (existing?.method as string | undefined);
          if (method) s.method = method;
          if (existing?.password) s.password = existing.password;
        }
        if (p === "wireguard" && existing) {
          if (existing.private_key) s.private_key = existing.private_key;
          if (existing.public_key) s.public_key = existing.public_key;
          if (existing.address) s.address = existing.address;
          if ((existing as { awg_address?: string }).awg_address) {
            s.awg_address = (existing as { awg_address?: string }).awg_address;
          }
          if (existing.preshared_key) s.preshared_key = existing.preshared_key;
        }
        const wgKind = wgKindForSubmit(!!protos.wireguard?.enabled, !!protos.amneziawg?.enabled);
        if (p === "wireguard" && wgKind) {
          s[NXPANEL_WG_KIND] = wgKind;
        }
        if (NATIVE_PROTOCOLS.includes(p as typeof NATIVE_PROTOCOLS[number])) {
          proxies[p] = Object.keys(s).length ? s : (p === "wireguard" && wgKind ? { [NXPANEL_WG_KIND]: wgKind } : {});
          inb[p] = p === "wireguard" && protos.amneziawg?.enabled && awgInboundTags.length
            ? protos.amneziawg.tags.filter((t) => awgInboundTags.includes(t))
            : [];
        } else {
          proxies[p] = s;
          inb[p] = v.tags;
        }
      });
      const body: any = {
        proxies,
        inbounds: inb,
        data_limit: dataLimitToBytes(dataLimitValue, dataLimitUnit),
        data_limit_reset_strategy: reset,
        note: note || "",
        client_profile: clientProfile,
      };
      if (mode === "edit") {
        body.routing_preset = routingPreset || null;
        body.dns_policy = dnsPreset ? { preset: dnsPreset } : null;
        body.speed_limit_up = speedUp.trim() ? parseInt(speedUp, 10) : null;
        body.speed_limit_down = speedDown.trim() ? parseInt(speedDown, 10) : null;
        body.device_limit = deviceLimit.trim() ? parseInt(deviceLimit, 10) : null;
        body.session_limit_minutes = sessionLimitMinutes.trim()
          ? parseInt(sessionLimitMinutes, 10)
          : null;
      } else {
        if (routingPreset) body.routing_preset = routingPreset;
        if (dnsPreset) body.dns_policy = { preset: dnsPreset };
        if (speedUp.trim()) body.speed_limit_up = parseInt(speedUp, 10);
        if (speedDown.trim()) body.speed_limit_down = parseInt(speedDown, 10);
        if (deviceLimit.trim()) body.device_limit = parseInt(deviceLimit, 10);
        if (sessionLimitMinutes.trim()) {
          body.session_limit_minutes = parseInt(sessionLimitMinutes, 10);
        }
      }
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

      if (isEnabled("user_portal") && portalEnabled) {
        body.portal_enabled = true;
        if (portalPassword.trim()) body.portal_password = portalPassword.trim();
      } else if (mode === "edit") {
        body.portal_enabled = portalEnabled;
      }

      if (mode === "create") {
        const finalUsername = username.trim() || generateRandomUsername();
        body.username = finalUsername;
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

  const availableProtos = PROTO_ORDER.filter((p) => {
    if (!protos[p]) return false;
    if (protos[p].enabled) return true;
    return protocolAssignable(
      p,
      inbounds.data ?? undefined,
      nodes.data ?? undefined,
      nativeCaps.data,
    );
  });

  const toggleWizardProto = (p: string) => {
    const enabling = !protos[p]?.enabled;
    const isNative = NATIVE_PROTOCOLS.includes(p as typeof NATIVE_PROTOCOLS[number]);
    const tags = enabling && !isNative ? defaultProtoInboundTags(p, inbounds.data ?? undefined) : [];
    setProto(p, {
      enabled: enabling,
      ...(enabling && tags.length ? { tags } : {}),
    });
  };

  const allProtosSelected = availableProtos.length > 0
    && availableProtos.every((p) => protos[p]?.enabled);

  const toggleAllProtos = () => {
    const on = !allProtosSelected;
    setProtos((prev) => {
      const next = { ...prev };
      for (const p of availableProtos) {
        if (!next[p]) continue;
        const isNative = NATIVE_PROTOCOLS.includes(p as typeof NATIVE_PROTOCOLS[number]);
        const tags = on && !isNative ? defaultProtoInboundTags(p, inbounds.data ?? undefined) : [];
        next[p] = {
          ...next[p],
          enabled: on,
          ...(on && tags.length ? { tags } : {}),
        };
      }
      return next;
    });
  };

  const wizardNext = () => {
    if (wizardStep === 1) {
      setWizardStep(2);
      return;
    }
    if (wizardStep === 2) {
      if (!enabledProtos.length) { toast.push(t("users.selectProtocol"), "error"); return; }
      setWizardStep(3);
    }
  };

  const showIdentity = !useWizard || wizardStep === 1;
  const showProtocols = useWizard ? wizardStep === 2 : formTab === "protocols";
  const showPlan = useWizard ? wizardStep === 3 : formTab === "plan";
  const showAdvanced = tabbedForm && formTab === "advanced";

  const protoWarnings = useMemo(() => {
    const lines: string[] = [];
    if (protos.hysteria2?.enabled && !hasHy2Node) lines.push(t("users.singboxNoHy2"));
    if (protos.tuic?.enabled && !hasTuicNode) lines.push(t("users.singboxNoTuic"));
    if (protos.anytls?.enabled && !hasAnytlsNode) lines.push(t("users.singboxNoAnytls"));
    if (protos.amneziawg?.enabled && !hasAwgNode) lines.push(t("users.awgNoNode"));
    if (protos.wireguard?.enabled && !hasPlainWgNode) lines.push(t("users.wgNoNode"));
    return lines;
  }, [protos, hasHy2Node, hasTuicNode, hasAnytlsNode, hasAwgNode, hasPlainWgNode, t]);

  const enabledProtoDetailRows = useMemo(
    () => availableProtos.filter((p) => {
      const v = protos[p];
      if (!v?.enabled) return false;
      if (p === "wireguard" || p === "hysteria2" || p === "tuic" || p === "anytls") return false;
      if (p === "amneziawg") return (inbounds.data?.amneziawg?.length || 0) > 0;
      return (inbounds.data?.[p]?.length || 0) > 0 || p === "vless" || p === "trojan";
    }),
    [availableProtos, protos, inbounds.data],
  );

  const renderProtoDetail = (p: string, v: ProtoState) => {
    const ibList = p === "amneziawg" ? (inbounds.data?.amneziawg || []) : (inbounds.data?.[p] || []);
    const ssRef = p === "shadowsocks"
      ? (deriveSsMethodFromInbounds(v.tags, ibList) || "")
      : "";
    return (
      <div key={p} className="nx-user-form-proto-detail">
        <div className="nx-user-form-proto-detail-head">{PROTO_LABEL[p] || p}</div>
        {p === "vless" && (
          <div className="nx-row" style={{ gap: 8 }}>
            <Select value={v.flow} onChange={(e: any) => setProto(p, { flow: e.target.value })} style={{ maxWidth: 240 }}>
              <option value="">{t("users.flowNone")}</option>
              {FLOWS.map((f) => <option key={f.v} value={f.v}>{f.labelKey ? t(f.labelKey) : f.v}</option>)}
            </Select>
          </div>
        )}
        {p === "trojan" && (
          <div className="nx-row" style={{ gap: 8 }}>
            <Select value={v.flow} onChange={(e: any) => setProto(p, { flow: e.target.value })} style={{ maxWidth: 240 }}>
              {FLOWS.map((f) => <option key={f.v} value={f.v}>{f.labelKey ? t(f.labelKey) : f.v}</option>)}
            </Select>
          </div>
        )}
        {p === "amneziawg" && ibList.length > 0 && (
          <div className="nx-user-form-inbound-chips">
            {ibList.map((i) => (
              <button
                key={i.tag}
                type="button"
                className={`nx-user-form-chip ${v.tags.includes(i.tag) ? "on" : ""}`}
                onClick={() => toggleTag(p, i.tag)}
              >
                {i.tag}
              </button>
            ))}
          </div>
        )}
        {p !== "amneziawg" && ibList.length > 0 && (
          <div className="nx-user-form-inbound-chips">
            {ibList.map((i) => {
              const compatible = p !== "shadowsocks" || !ssRef || inboundMatchesSsMethod(i.ss_method, ssRef);
              return (
                <button
                  key={i.tag}
                  type="button"
                  disabled={!compatible}
                  title={compatible ? undefined : t("users.ssInboundMismatch")}
                  className={`nx-user-form-chip ${v.tags.includes(i.tag) ? "on" : ""}`}
                  onClick={() => compatible && toggleTag(p, i.tag)}
                >
                  {i.tag}
                  {p === "shadowsocks" && i.ss_method ? ` · ${i.ss_method}` : ""}
                </button>
              );
            })}
          </div>
        )}
        {p === "shadowsocks" && (
          <div className="nx-faint" style={{ fontSize: 12 }}>
            {v.tags.length
              ? t("users.ssMethodValue", { method: deriveSsMethodFromInbounds(v.tags, ibList) || v.method })
              : t("users.ssMethodFromInbound")}
          </div>
        )}
      </div>
    );
  };

  const editStatusOptions = mode === "edit"
    ? (["active", "on_hold", "disabled"] as const)
    : (["active", "on_hold"] as const);

  return (
    <Drawer
      open
      wide={useWizard || mode === "edit"}
      hideHead={mode === "edit"}
      overlayClassName={useWizard ? "centered" : ""}
      drawerClassName={useWizard ? "wizard-mode" : `nx-user-form-drawer${mode === "edit" ? " nx-user-edit" : ""}`}
      title={mode === "create" ? t("common.create") : t("common.edit")}
      onClose={onClose}
    >
      <div className={`nx-stack nx-user-form ${useWizard ? "compact" : ""} ${tabbedForm ? "nx-user-form-tabbed" : ""} ${mode === "edit" ? "is-edit" : ""}`}>
        {mode === "edit" && (
          <header className="nx-ue-top">
            <div className="nx-ue-top-main">
              {loadingEdit ? (
                <div className="nx-uf-loading" style={{ padding: 0 }}>{t("common.loading")}</div>
              ) : (
                <>
                  <div className="nx-ue-eyebrow">{t("common.edit")}</div>
                  <h2 className="nx-ue-title" dir="ltr">{editProfile?.username || user?.username}</h2>
                  <div className="nx-ue-sub">
                    <span className={`nx-ue-dot ${editProfile?.online ? "live" : statusTone(editProfile?.status || status)}`} />
                    <span>
                      {editProfile?.online
                        ? t("users.stats.online")
                        : t(`users.status.${editProfile?.status || status}`, editProfile?.status || status)}
                    </span>
                    <span className="nx-ue-sep" aria-hidden>·</span>
                    <span dir="ltr">
                      {formatBytes(editProfile?.used_traffic ?? 0)}
                      {" / "}
                      {(editProfile?.data_limit) ? formatBytes(editProfile.data_limit) : t("users.unlimited")}
                    </span>
                    <span className="nx-ue-sep" aria-hidden>·</span>
                    <span>
                      {editProfile?.expire
                        ? relativeExpiryLabel(editProfile.expire, t)
                        : t("users.never")}
                    </span>
                  </div>
                </>
              )}
            </div>
            <button type="button" className="nx-btn icon ghost nx-ue-close" onClick={onClose} aria-label={t("common.close")}>
              <IcClose />
            </button>
          </header>
        )}

        {tabbedForm && !loadingEdit && (
          <div className={`nx-user-form-tabstrip${mode === "edit" ? " nx-ue-tabs" : ""}`} role="tablist">
            {(mode === "edit"
              ? (["plan", "protocols", "advanced"] as UserFormTab[])
              : (["protocols", "plan", "advanced"] as UserFormTab[])
            ).map((tab) => (
              <button
                key={tab}
                type="button"
                role="tab"
                aria-selected={formTab === tab}
                className={`nx-user-form-tab ${formTab === tab ? "active" : ""}`}
                onClick={() => setFormTab(tab)}
              >
                {t(`users.formTab${tab.charAt(0).toUpperCase()}${tab.slice(1)}`)}
              </button>
            ))}
          </div>
        )}
        {useWizard && (
          <div className="nx-wizard-steps">
            {WIZARD_STEPS.map((key, idx) => {
              const n = idx + 1;
              const cls = n === wizardStep ? "active" : n < wizardStep ? "done" : "";
              return (
                <Fragment key={key}>
                  {idx > 0 && <div className={`nx-wizard-connector ${n <= wizardStep ? "done" : ""}`} />}
                  <div className={`nx-wizard-step ${cls}`}>
                    <span className="nx-wizard-step-num">{n < wizardStep ? "✓" : n}</span>
                    <span>{t(`users.${key}`)}</span>
                  </div>
                </Fragment>
              );
            })}
          </div>
        )}

        <div className={useWizard ? "nx-user-form-main" : "nx-uf-scroll"}>
        {mode === "create" && templateId ? (
          <Callout tone="info">{t("users.templateHint")}</Callout>
        ) : null}
        {showIdentity && mode === "create" && (
          <>
            {templateId ? (
              <Field label={t("common.username")} hint={t("users.usernameHint")}>
                <Input value={username} onChange={(e: any) => setUsername(e.target.value)} autoFocus />
              </Field>
            ) : (
              <Field label={t("common.username")} hint={t("users.usernameAutoHint")}>
                <div className="nx-input-group">
                  <Input
                    value={username}
                    onChange={(e: any) => setUsername(e.target.value)}
                    placeholder={t("users.usernameHint")}
                    dir="ltr"
                    autoFocus
                  />
                  <button
                    type="button"
                    className="nx-input-group-btn"
                    title={t("users.usernameRegenerate")}
                    aria-label={t("users.usernameRegenerate")}
                    onClick={() => setUsername(generateRandomUsername())}
                  >
                    <IcRefresh className="nx-ico" />
                  </button>
                </div>
              </Field>
            )}
            {!useWizard && templates.data && templates.data.length > 0 && (
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

        {showProtocols && (
        <div className="nx-user-form-pane">
          {(useWizard || tabbedForm) && (
            <div className="nx-uf-pane-head">
              <p className="nx-user-form-proto-lead">
                {useWizard ? t("users.wizardPickProtoHint") : t("users.formTabProtocolsHint")}
              </p>
              <div className="nx-row" style={{ gap: 8, flexWrap: "wrap" }}>
                {availableProtos.length > 0 && (
                  <Button size="sm" variant="ghost" type="button" onClick={toggleAllProtos}>
                    {allProtosSelected ? t("users.deselectAllProtos") : t("users.selectAllProtos")}
                  </Button>
                )}
                {enabledProtos.length > 0 && (
                  <Pill tone="accent">{t("users.wizardSelectedCount", { n: enabledProtos.length })}</Pill>
                )}
              </div>
            </div>
          )}
          {protoWarnings.map((line) => (
            <div key={line} className="nx-user-form-warn-line">{line}</div>
          ))}
          {inbounds.loading ? <SkeletonRows rows={2} cols={1} />
            : !Object.keys(protos).length ? <div className="nx-faint" style={{ fontSize: 12 }}>{t("common.noData")}</div>
            : !availableProtos.length ? (
              <EmptyState
                title={t("users.noProtocolsAvailable")}
                desc={t("users.noProtocolsAvailableHint")}
                action={<Link to="/connection?tab=inbounds"><Button variant="primary">{t("users.openConnectionHub")}</Button></Link>}
              />
            ) : (
              <>
                <div className="nx-proto-pick">
                  {availableProtos.map((p) => {
                    const vis = PROTO_VISUAL[p] || { icon: "·", hue: "var(--nx-accent)" };
                    const selected = !!protos[p]?.enabled;
                    return (
                      <button
                        key={p}
                        type="button"
                        className={`nx-proto-pick-card ${selected ? "selected" : ""}`}
                        style={{ "--proto-hue": vis.hue } as React.CSSProperties}
                        onClick={() => toggleWizardProto(p)}
                      >
                        <span className="nx-proto-pick-check">✓</span>
                        <span className="nx-proto-icon">{vis.icon}</span>
                        <b>{PROTO_LABEL[p] || p}</b>
                        <small>
                          {NATIVE_PROTOCOLS.includes(p as typeof NATIVE_PROTOCOLS[number])
                            ? t("users.wgNativePeer")
                            : t("users.inboundCount", { n: inbounds.data?.[p]?.length || 0 })}
                        </small>
                      </button>
                    );
                  })}
                </div>
                {enabledProtoDetailRows.length > 0 && (
                  <div className="nx-user-form-proto-details">
                    <div className="nx-ue-label">{t("users.inboundSettings")}</div>
                    {enabledProtoDetailRows.map((p) => renderProtoDetail(p, protos[p]))}
                  </div>
                )}
              </>
            )}
        </div>
        )}

        {showPlan && (
        <div className={`nx-user-form-pane${mode === "edit" ? " nx-ue-pane" : ""}`}>
        {useWizard && wizardStep === 3 && (
          <Callout tone="info" title={t("users.wizardReview")}>
            <b>{username.trim() || t("users.usernameWillAuto")}</b> · {enabledProtos.map(([p]) => PROTO_LABEL[p] || p).join(", ")}
          </Callout>
        )}

          {mode === "edit" ? (
            <>
              <div className="nx-ue-field">
                <div className="nx-ue-label">{t("common.status")}</div>
                <div className="nx-ue-seg" role="group">
                  {editStatusOptions.map((s) => (
                    <button
                      key={s}
                      type="button"
                      className={status === s ? "on" : ""}
                      onClick={() => setStatus(s)}
                    >
                      {t(`users.status.${s}`)}
                    </button>
                  ))}
                </div>
              </div>

              <div className="nx-ue-field">
                <div className="nx-ue-label">{t("users.dataLimit")}</div>
                <div className="nx-ue-inline">
                  <Input
                    type="number"
                    min="0"
                    step={dataLimitUnit === "MB" ? "1" : "0.001"}
                    value={dataLimitValue}
                    placeholder={t("users.unlimited")}
                    onChange={(e: any) => setDataLimitValue(e.target.value)}
                    dir="ltr"
                  />
                  <Select
                    value={dataLimitUnit}
                    onChange={(e: any) => setDataLimitUnit(e.target.value as DataLimitUnit)}
                  >
                    <option value="MB">MB</option>
                    <option value="GB">GB</option>
                  </Select>
                </div>
                <p className="nx-ue-help">{t("users.dataLimitHint")}</p>
              </div>

              <div className="nx-ue-field">
                <div className="nx-ue-label">{t("users.expire")}</div>
                <label className="nx-ue-check">
                  <Checkbox checked={noExpire} onChange={() => setNoExpire((u) => !u)} />
                  <span>{t("users.never")}</span>
                </label>
                {!noExpire && (
                  <>
                    <Input
                      type="date"
                      className="nx-input-date"
                      value={expireDate}
                      onChange={(e: any) => setExpireDate(e.target.value)}
                      dir="ltr"
                      inputMode="none"
                    />
                    <div className="nx-ue-chips">
                      {[30, 60, 90].map((d) => (
                        <button key={d} type="button" className="nx-ue-chip" onClick={() => preset(d)}>+{d}d</button>
                      ))}
                    </div>
                  </>
                )}
              </div>

              <div className="nx-ue-grid">
                <Field label={t("users.resetStrategy")}>
                  <Select value={reset} onChange={(e: any) => setReset(e.target.value)}>
                    {["no_reset", "day", "week", "month", "year"].map((r) => <option key={r} value={r}>{t(`users.resetStrategies.${r}`, r)}</option>)}
                  </Select>
                </Field>
                <Field label={t("users.clientProfile")}>
                  <Select value={clientProfile} onChange={(e: any) => setClientProfile(e.target.value)}>
                    {["normal", "gamer", "trader"].map((p) => (
                      <option key={p} value={p}>{t(`users.profile.${p}`)}</option>
                    ))}
                  </Select>
                </Field>
              </div>

              <div className="nx-ue-divider" />

              <div className="nx-ue-grid">
                <Field label={t("users.speedUp")}>
                  <Input type="number" min={0} placeholder="Mbps" value={speedUp} onChange={(e: any) => setSpeedUp(e.target.value)} dir="ltr" />
                </Field>
                <Field label={t("users.speedDown")}>
                  <Input type="number" min={0} placeholder="Mbps" value={speedDown} onChange={(e: any) => setSpeedDown(e.target.value)} dir="ltr" />
                </Field>
                <Field label={t("users.deviceLimit")} hint={t("users.deviceLimitHint")}>
                  <Input type="number" min={0} value={deviceLimit} onChange={(e: any) => setDeviceLimit(e.target.value)} placeholder={t("common.none")} dir="ltr" />
                </Field>
              </div>
            </>
          ) : (
            <>
              <div className="nx-user-form-grid">
                <Field label={t("users.dataLimit")} hint={t("users.dataLimitHint")}>
                  <div className="nx-row" style={{ gap: 8 }}>
                    <Input
                      type="number"
                      min="0"
                      step={dataLimitUnit === "MB" ? "1" : "0.001"}
                      value={dataLimitValue}
                      placeholder={t("users.unlimited")}
                      onChange={(e: any) => setDataLimitValue(e.target.value)}
                      style={{ flex: 1 }}
                      dir="ltr"
                    />
                    <Select
                      value={dataLimitUnit}
                      onChange={(e: any) => setDataLimitUnit(e.target.value as DataLimitUnit)}
                      style={{ width: 88 }}
                    >
                      <option value="MB">MB</option>
                      <option value="GB">GB</option>
                    </Select>
                  </div>
                </Field>
                <Field label={t("common.status")}>
                  <Select value={status} onChange={(e: any) => setStatus(e.target.value)}>
                    <option value="active">{t("users.status.active")}</option>
                    <option value="on_hold">{t("users.status.on_hold")}</option>
                  </Select>
                </Field>
                <Field label={t("users.expire")}>
                  <div className="nx-row" style={{ gap: 8, flexWrap: "wrap" }}>
                    <Input type="date" value={noExpire ? "" : expireDate} disabled={noExpire} onChange={(e: any) => setExpireDate(e.target.value)} style={{ flex: 1, minWidth: 140, maxWidth: 200 }} />
                    <label className="nx-row" style={{ gap: 6, fontSize: 12, whiteSpace: "nowrap" }}>
                      <Checkbox checked={noExpire} onChange={() => setNoExpire((u) => !u)} /> {t("users.never")}
                    </label>
                  </div>
                  {!noExpire && (
                    <div className="nx-uf-presets">
                      {[30, 60, 90].map((d) => (
                        <button key={d} type="button" className="nx-uf-preset" onClick={() => preset(d)}>{d}d</button>
                      ))}
                    </div>
                  )}
                </Field>
                <Field label={t("users.resetStrategy")}>
                  <Select value={reset} onChange={(e: any) => setReset(e.target.value)}>
                    {["no_reset", "day", "week", "month", "year"].map((r) => <option key={r} value={r}>{t(`users.resetStrategies.${r}`, r)}</option>)}
                  </Select>
                </Field>
                {(!useWizard || wizardStep === 3) && (
                  <Field label={t("users.clientProfile")}>
                    <Select value={clientProfile} onChange={(e: any) => setClientProfile(e.target.value)}>
                      {["normal", "gamer", "trader"].map((p) => (
                        <option key={p} value={p}>{t(`users.profile.${p}`)}</option>
                      ))}
                    </Select>
                  </Field>
                )}
              </div>
              {(!useWizard || wizardStep === 3) && (
                <div className="nx-user-form-grid" style={{ marginTop: 8 }}>
                  <Field label={t("users.speedUp")}>
                    <Input type="number" min={0} placeholder="Mbps" value={speedUp} onChange={(e: any) => setSpeedUp(e.target.value)} dir="ltr" />
                  </Field>
                  <Field label={t("users.speedDown")}>
                    <Input type="number" min={0} placeholder="Mbps" value={speedDown} onChange={(e: any) => setSpeedDown(e.target.value)} dir="ltr" />
                  </Field>
                  <Field label={t("users.deviceLimit")} hint={t("users.deviceLimitHint")}>
                    <Input type="number" min={0} value={deviceLimit} onChange={(e: any) => setDeviceLimit(e.target.value)} placeholder={t("common.none")} dir="ltr" />
                  </Field>
                </div>
              )}
            </>
          )}
        </div>
        )}

        {showAdvanced && (
        <div className={`nx-user-form-pane${mode === "edit" ? " nx-ue-pane" : ""}`}>
          {mode === "edit" && canWrite && (
            <div className="nx-ue-secure">
              <div className="nx-ue-label">{t("users.subSecuritySection")}</div>
              <p className="nx-ue-help">{t("users.subSecurityHint")}</p>
              {subToken ? (
                <Field label={t("users.subToken")} hint={t("users.subTokenHint")}>
                  <CopyField value={subToken} />
                </Field>
              ) : null}
              {subscriptionUrl ? (
                <Field label={t("users.subscriptionLink")}>
                  <CopyField value={absoluteUrl(subscriptionUrl)} />
                </Field>
              ) : null}
              {credentialLines.length > 0 ? (
                <Field label={t("users.proxyCredentials")}>
                  <div className="nx-uf-creds">
                    {credentialLines.map((line) => <div key={line}>{line}</div>)}
                  </div>
                </Field>
              ) : null}
              {subRevokedAt ? (
                <Callout tone="warn">
                  {t("users.subRevokedAt", { date: formatDate(subRevokedAt) })}
                </Callout>
              ) : null}
              <div className="nx-uf-security-actions">
                <Button size="sm" variant="danger" disabled={credBusy || loadingEdit} onClick={handleRevokeSub}>
                  {t("users.revokeSubFull")}
                </Button>
                <Button size="sm" variant="ghost" disabled={credBusy || loadingEdit} onClick={handleRotateSub}>
                  {t("users.rotateSubLink")}
                </Button>
              </div>
            </div>
          )}
          <div className={mode === "edit" ? "nx-ue-grid" : "nx-user-form-grid"}>
            <Field label={t("users.sessionLimit", { defaultValue: "Session limit (minutes)" })}>
              <Input type="number" min="0" value={sessionLimitMinutes} onChange={(e: any) => setSessionLimitMinutes(e.target.value)} placeholder={t("common.none")} />
            </Field>
            {routingPresets.data && (
              <Field label={t("users.routingPreset", { defaultValue: "Routing preset" })}>
                <Select value={routingPreset} onChange={(e: any) => setRoutingPreset(e.target.value)}>
                  <option value="">{t("common.none", { defaultValue: "None" })}</option>
                  {Object.entries(routingPresets.data.presets || {}).map(([id, meta]) => (
                    <option key={id} value={id}>{meta.label || id}</option>
                  ))}
                </Select>
              </Field>
            )}
            {dnsPresets.data && (
              <Field label={t("users.dnsPreset", { defaultValue: "DNS policy" })}>
                <Select value={dnsPreset} onChange={(e: any) => setDnsPreset(e.target.value)}>
                  <option value="">{t("common.none", { defaultValue: "None" })}</option>
                  {Object.entries(dnsPresets.data.presets || {}).map(([id, meta]) => (
                    <option key={id} value={id}>{meta.label || id}</option>
                  ))}
                </Select>
              </Field>
            )}
            <div style={{ gridColumn: "1 / -1" }}>
              <Field label={t("users.noteLabel")}>
                <Input value={note} onChange={(e: any) => setNote(e.target.value)} placeholder={t("common.optional")} />
              </Field>
            </div>
          </div>
          {isEnabled("user_portal") && (
            <div className="nx-ue-field" style={{ marginTop: 8 }}>
              <label className="nx-ue-check">
                <Checkbox checked={portalEnabled} onChange={() => setPortalEnabled((v) => !v)} />
                <span>{t("users.portalEnabled")}</span>
              </label>
              {portalEnabled && (
                <Field label={t("users.portalPassword")} hint={mode === "edit" ? t("users.portalPasswordHint") : t("users.portalCreateHint")}>
                  <Input
                    type="password"
                    value={portalPassword}
                    onChange={(e: any) => setPortalPassword(e.target.value)}
                    placeholder={mode === "edit" ? t("users.portalPasswordPlaceholder") : ""}
                  />
                </Field>
              )}
            </div>
          )}
        </div>
        )}

        </div>

        <div className="nx-user-form-foot">
          <div>
            {useWizard && wizardStep > 1 && (
              <Button variant="ghost" onClick={() => setWizardStep((s) => s - 1)}>{t("users.prev")}</Button>
            )}
          </div>
          <div className="nx-row" style={{ gap: 10 }}>
            <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
            {useWizard && wizardStep < 3 ? (
              <Button variant="primary" onClick={wizardNext}>{t("users.next")}</Button>
            ) : (
              <Button variant="primary" disabled={busy || loadingEdit} onClick={submit}>
                {mode === "create" ? t("common.create") : t("common.save")}
              </Button>
            )}
          </div>
        </div>
        {useWizard && (
          <div className="nx-faint nx-user-form-wizard-hint">{t("users.wizardExpertLink")}</div>
        )}
      </div>
    </Drawer>
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
  const { isEnabled } = useApp();
  const { data, loading, error, reload } = useFetch<UserItem>(() => api.get(`/user/${encodeURIComponent(username)}`), [username]);
  const [tab, setTab] = useState<"subscription" | "configs">("subscription");
  const [activeLink, setActiveLink] = useState(0);
  const [sellPlan, setSellPlan] = useState(false);
  const billingOn = isEnabled("billing");

  const [showOtherLinks, setShowOtherLinks] = useState(false);

  const pct = data ? usagePct(data.used_traffic, data.data_limit) : 0;
  const remaining = data ? remainingPct(data.used_traffic, data.data_limit) : null;
  // A per-inbound/per-panel endpoint that actually matches this user's own
  // inbounds (e.g. a migrated panel's domain, or a dedicated per-inbound
  // Listen Domain) is the one link that's actually correct for them — show
  // that as THE main link instead of the generic panel-default one whenever
  // it exists, so admins don't have to dig through the full endpoint list.
  const recommended = (data?.subscription_urls || []).find((u) => u.recommended && u.url);
  const subUrl = absoluteUrl(
    recommended?.url || data?.public_subscription_url || data?.subscription_url,
  );
  const clientImportUrl = absoluteUrl(
    data?.client_subscription_url
      || recommended?.import_url
      || subUrl,
  );
  const profileTitle = data?.subscription_profile_title?.trim() || "NexusPanel";
  const otherLinks = (data?.subscription_urls || []).filter((u) => {
    const uUrl = u.url ? absoluteUrl(u.url) : "";
    return uUrl && uUrl !== subUrl;
  });
  const subscribeBrowserUrl = resolveSubscribeBrowserUrl(subUrl);
  const links = data?.links || [];
  const wgStacks = data ? userWgStackLabels(data.proxies?.wireguard as { address?: string; awg_address?: string; nexusPanelKind?: string }) : [];
  const hasWireguard = wgStacks.includes("wireguard");
  const hasAmneziaWg = wgStacks.includes("amneziawg");
  const wgUrl = resolveWgUrl(subUrl, "plain");
  const awgUrl = resolveWgUrl(subUrl, "awg");

  const initials = username.slice(0, 2).toUpperCase();

  const share = async (url: string) => {
    if (navigator.share) {
      try { await navigator.share({ title: `NexusPanel — ${username}`, url }); return; } catch { /* user cancelled */ }
    }
    const ok = await copyToClipboard(url);
    toast.push(ok ? t("common.copiedToClipboard") : t("common.copyFailed"), ok ? "success" : "error");
  };

  return (
    <Drawer open title={t("users.title")} onClose={onClose}>
      {loading ? <SkeletonRows rows={6} cols={1} />
        : error || !data ? (
          <EmptyState
            title={t("common.error")}
            desc={error || t("common.noData")}
            action={<Button onClick={reload}>{t("common.retry")}</Button>}
          />
        ) : (
        <>
          {/* Hero */}
          <div className="nx-user-hero">
            <div className="nx-avatar">{initials}</div>
            <div style={{ minWidth: 140, flex: 1 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                <span className="nx-user-hero-name nx-truncate">{data.username}</span>
                <span style={{ flexShrink: 0 }}>
                  <Pill tone={statusTone(data.status)} dot>{t(`users.status.${data.status}`, data.status)}</Pill>
                </span>
              </div>
              {data.admin ? (
                <div className="nx-user-hero-meta">{t("users.byAdmin", { admin: data.admin.username })}</div>
              ) : null}
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
              {billingOn ? (
                <Button size="sm" variant="primary" onClick={() => setSellPlan(true)}>{t("users.sellPlan")}</Button>
              ) : null}
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
            {(data.overage_traffic ?? 0) > 0 ? (
              <div className="nx-statbox">
                <div className="nx-statbox-k">{t("users.overage")}</div>
                <div className="nx-statbox-v" style={{ color: "var(--nx-danger, #ef4444)" }}>{formatBytes(data.overage_traffic!)}</div>
                <div className="nx-faint" style={{ fontSize: 11, marginTop: 4 }}>{t("users.overageHint")}</div>
              </div>
            ) : null}
            <div className="nx-statbox">
              <div className="nx-statbox-k">{t("users.remaining")}</div>
              <div className="nx-statbox-v">{remaining !== null ? `${remaining.toFixed(0)}%` : "∞"}</div>
              {data.data_limit ? <div style={{ marginTop: 8 }}><UsageBar pct={pct} /></div> : null}
            </div>
            <div className="nx-statbox">
              <div className="nx-statbox-k">{t("users.expire")}</div>
              <div className="nx-statbox-v">{data.expire ? formatDate(data.expire, i18n.language) : t("users.never")}</div>
              {data.expire ? <div className="nx-faint" style={{ fontSize: 11, marginTop: 4 }}>{(() => { const r = relativeExpiry(data.expire); return r.days !== null && r.days < 0 ? t("users.expired") : relativeExpiryLabel(data.expire, t); })()}</div> : null}
            </div>
            <div className="nx-statbox">
              <div className="nx-statbox-k">{t("users.online")}</div>
              <div className="nx-statbox-v">{data.online_at ? formatDate(new Date(data.online_at).getTime() / 1000, i18n.language) : "—"}</div>
            </div>
          </div>

          {isEnabled("user_portal") && data.portal_enabled ? (
            <div style={{ marginBottom: 14 }}>
              <Callout tone="ok" title={t("users.portalEnabled")}>
                <a href="/portal/" target="_blank" rel="noreferrer" className="nx-link">{t("users.openPortal")}</a>
              </Callout>
            </div>
          ) : null}

          {/* Tabs */}
          {(subUrl || links.length > 0) && (
            <>
              <div className="nx-tabs">
                {subUrl && <button className={`nx-tab ${tab === "subscription" ? "active" : ""}`} onClick={() => setTab("subscription")}>{t("users.subscription")}</button>}
                {links.length > 0 && <button className={`nx-tab ${tab === "configs" ? "active" : ""}`} onClick={() => setTab("configs")}>{t("users.configs")} · {links.length}</button>}
              </div>

              {tab === "subscription" && subUrl && (
                <div className="nx-stack" style={{ alignItems: "stretch", gap: 14 }}>
                  <Callout tone="info" title={t("users.subUrlHintTitle")}>
                    <p style={{ margin: "0 0 10px", fontSize: 13 }}>{t("users.subUrlHintBody")}</p>
                  </Callout>
                  <div className="nx-center"><div className="nx-qr-frame"><QR value={subUrl} size={200} /></div></div>
                  <CopyField label={t("users.subUrlClient")} value={subUrl} />
                  {profileTitle && profileTitle !== "NexusPanel" && (
                    <p className="nx-faint" style={{ fontSize: 12, margin: 0 }}>
                      {t("users.subProfileTitleHint")}: <strong dir="ltr">{profileTitle}</strong>
                    </p>
                  )}
                  {otherLinks.length > 0 && (
                    <div className="nx-stack" style={{ gap: 8 }}>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setShowOtherLinks((v) => !v)}
                      >
                        {showOtherLinks
                          ? t("users.hideOtherLinks")
                          : t("users.showOtherLinks", { n: otherLinks.length })}
                      </Button>
                      {showOtherLinks && (
                        <>
                          <p className="nx-faint" style={{ fontSize: 12, margin: "0 0 4px" }}>
                            {t("users.otherLinksHint")}
                          </p>
                          {otherLinks.map((u) => (
                            <CopyField
                              key={u.slug + u.url}
                              label={[u.label, u.inbound_tag, u.export_mode]
                                .filter(Boolean)
                                .join(" · ")}
                              value={absoluteUrl(u.url)}
                            />
                          ))}
                        </>
                      )}
                    </div>
                  )}
                  {subscribeBrowserUrl && subscribeBrowserUrl !== subUrl && (
                    <>
                      <CopyField label={t("users.subUrlBrowser")} value={subscribeBrowserUrl} />
                      <div className="nx-share-row">
                        <a className="nx-btn" href={subscribeBrowserUrl} target="_blank" rel="noreferrer">
                          <IcExternal className="nx-ico" /> {t("users.openSubscribePage")}
                        </a>
                      </div>
                    </>
                  )}
                  <div className="nx-share-row">
                    <a className="nx-btn" href={subUrl} target="_blank" rel="noreferrer"><IcExternal className="nx-ico" /> {t("users.open")}</a>
                    <Button onClick={() => share(subUrl)}><IcShare className="nx-ico" /> {t("users.share")}</Button>
                  </div>
                  {(hasWireguard || hasAmneziaWg) && (wgUrl || awgUrl) && (
                    <div className="nx-share-row">
                      {hasWireguard && wgUrl && (
                        <a className="nx-btn" href={wgUrl} download={`${data.username}.conf`}>
                          <IcExternal className="nx-ico" /> {t("users.downloadWireguard")}
                        </a>
                      )}
                      {hasAmneziaWg && awgUrl && (
                        <a className="nx-btn" href={awgUrl} download={`${data.username}-awg.conf`}>
                          <IcExternal className="nx-ico" /> {t("users.downloadAwg")}
                        </a>
                      )}
                    </div>
                  )}
                </div>
              )}

              {tab === "configs" && links.length > 0 && (
                <div className="nx-stack" style={{ gap: 12 }}>
                  <div className="nx-config-account-meta">
                    <span>{t("users.used")}: <b>{formatBytes(data.used_traffic)}</b>{data.data_limit ? ` / ${formatBytes(data.data_limit)}` : ` · ${t("users.unlimited")}`}</span>
                    <span>{t("users.expire")}: <b>{data.expire ? formatDate(data.expire, i18n.language) : t("users.never")}</b></span>
                  </div>
                  <p className="nx-faint" style={{ fontSize: 12, margin: 0 }}>{t("users.configAccountMeta")}</p>
                  <div className="nx-config-list">
                    {(data.link_items?.length ? data.link_items : links.map((link) => ({ link, protocol: proxyKind(link), remark: "", region_flag: "", region_name: "" }))).map((item, i) => (
                      <div
                        key={i}
                        className={`nx-config-list-item ${activeLink === i ? "active" : ""}`}
                      >
                        <button
                          type="button"
                          className="nx-config-list-main"
                          onClick={() => setActiveLink(i)}
                        >
                          <span className="nx-config-list-proto">{String(item.protocol || proxyKind(item.link)).toUpperCase()}</span>
                          {item.region_flag ? <span className="nx-config-list-flag">{item.region_flag}</span> : null}
                          <span className="nx-config-list-title">{item.remark || item.region_name || `${proxyKind(item.link)} #${i + 1}`}</span>
                        </button>
                        <button
                          type="button"
                          className="nx-config-copy"
                          title={t("common.copy")}
                          aria-label={t("common.copy")}
                          onClick={async () => {
                            const ok = await copyToClipboard(item.link);
                            toast.push(ok ? t("common.copiedToClipboard") : t("common.copyFailed"), ok ? "success" : "error");
                          }}
                        >
                          <IcCopy size={15} />
                        </button>
                      </div>
                    ))}
                  </div>
                  <div className="nx-center"><div className="nx-qr-frame"><QR value={links[activeLink]} size={170} /></div></div>
                </div>
              )}
            </>
          )}
        </>
      )}
      {sellPlan && billingOn ? (
        <SellPlanModal username={username} onClose={() => setSellPlan(false)} onDone={() => { setSellPlan(false); onClose(); }} />
      ) : null}
    </Drawer>
  );
};

const SellPlanModal: FC<{ username: string; onClose: () => void; onDone: () => void }> = ({ username, onClose, onDone }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const { data: plans, loading } = useFetch<Plan[]>(() => api.get("/plans?enabled_only=true"), []);
  const [planId, setPlanId] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    const id = parseInt(planId, 10);
    if (!id) return;
    setBusy(true);
    try {
      await api.post(`/user/${encodeURIComponent(username)}/apply-plan`, { plan_id: id });
      toast.push(t("users.sellPlanDone"), "success");
      onDone();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open title={t("users.sellPlan")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={busy || !planId} onClick={submit}>{t("users.sellPlanConfirm")}</Button></>}>
      {loading ? <SkeletonRows rows={2} cols={1} /> : !plans?.length ? (
        <Callout tone="warn">{t("users.sellPlanEmpty")}</Callout>
      ) : (
        <Field label={t("billing.tabPlans")}>
          <Select value={planId} onChange={(e: any) => setPlanId(e.target.value)}>
            <option value="">{t("users.sellPlanChoose")}</option>
            {plans.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} — {p.price.toLocaleString()} · {p.duration_days ? `${p.duration_days}d` : "∞"}
              </option>
            ))}
          </Select>
        </Field>
      )}
    </Modal>
  );
};
