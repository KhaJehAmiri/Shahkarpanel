import { FC, ReactNode, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { CoreStats, MrrSummary, RealtimeStats, ResellerWorkspace, SystemStats, TopUser } from "../api/types";
import { usePanelUpdate } from "../context/UpdateContext";
import { useApp } from "../context/AppContext";
import { useCopilot } from "../copilot/CopilotContext";
import { useFetch, useLiveReload, usePolling } from "../lib/useFetch";
import { formatBytes, formatSpeed } from "../lib/format";
import { PageHeader } from "../components/Shell";
import { HealthChecklist } from "../components/HealthChecklist";
import { SystemVitals } from "../components/viz/SystemVitals";
import { Card, CardHead, Stat, SkeletonRows, Pill, Callout, Button, EmptyState, useToast } from "../components/ui";
import { RankBars } from "../components/charts";
import { IcUsers, IcServer, IcBolt, IcWallet, IcCheck, IcAlert, IcRefresh, IcMonitor } from "../components/icons";

type NodeUsageRow = { node_id: number | null; node_name: string; uplink: number; downlink: number };
type ProtocolUsageRow = { protocol: string; used_traffic: number };

type KpiTone = "accent" | "info" | "ok" | "warn" | "danger";

const KpiTile: FC<{
  label: string;
  value: ReactNode;
  icon: ReactNode;
  tone?: KpiTone;
  sub?: ReactNode;
  to?: string;
}> = ({ label, value, icon, tone = "accent", sub, to }) => {
  const body = (
    <>
      <span className="nx-kpi-chip" aria-hidden>{icon}</span>
      <div className="nx-kpi-main">
        <span className="nx-kpi-label">{label}</span>
        <span className="nx-kpi-value">{value}</span>
        {sub ? <span className="nx-kpi-sub">{sub}</span> : null}
      </div>
    </>
  );
  const cls = `nx-kpi nx-kpi-${tone}${to ? " nx-kpi-link" : ""}`;
  return to ? <Link to={to} className={cls}>{body}</Link> : <div className={cls}>{body}</div>;
};

function formatUptime(seconds?: number): string {
  if (!seconds || seconds <= 0) return "—";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return h > 0 ? `${d}d ${h}h` : `${d}d`;
  if (h > 0) return m > 0 ? `${h}h ${m}m` : `${h}h`;
  if (m > 0) return `${m}m`;
  return `${Math.floor(seconds)}s`;
}

const UptimeCard: FC<{
  xray?: number;
  os?: number;
  node?: number;
  showNode?: boolean;
}> = ({ xray, os, node, showNode }) => {
  const { t } = useTranslation();
  const items: { key: string; label: string; icon: ReactNode; value?: number; live: boolean }[] = [
    { key: "xray", label: "Xray", icon: <IcBolt />, value: xray, live: !!xray && xray > 0 },
    { key: "os", label: t("overview.uptimeOs"), icon: <IcMonitor />, value: os, live: !!os && os > 0 },
  ];
  if (showNode) items.push({ key: "node", label: t("overview.nodes"), icon: <IcServer />, value: node, live: !!node && node > 0 });
  return (
    <Card className="nx-glass-card">
      <CardHead title={t("overview.uptime")} />
      <div className="nx-uptime-row">
        {items.map((it) => (
          <div key={it.key} className="nx-uptime-cell">
            <span className={`nx-uptime-ico${it.live ? " live" : ""}`} aria-hidden>{it.icon}</span>
            <div className="nx-uptime-main">
              <span className="nx-uptime-label">{it.label}</span>
              <span className="nx-uptime-value">{formatUptime(it.value)}</span>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
};

const OverallSpeedCard: FC<{
  up: number;
  down: number;
  totalUp?: number;
  totalDown?: number;
  stale?: boolean;
}> = ({ up, down, totalUp, totalDown, stale }) => {
  const { t } = useTranslation();
  return (
    <Card className="nx-glass-card">
      <CardHead
        title={t("overview.overallSpeed")}
        actions={stale ? <Pill tone="warn" dot>{t("overview.liveStale")}</Pill> : <Pill tone="ok" dot>{t("overview.live")}</Pill>}
      />
      <div className="nx-speed-row">
        <div className="nx-speed-cell">
          <span className="nx-speed-label"><span className="nx-speed-arrow up">↑</span> {t("overview.upload")}</span>
          <span className="nx-speed-value">{formatSpeed(up)}</span>
          {totalUp != null && <span className="nx-speed-total">{formatBytes(totalUp)}</span>}
        </div>
        <div className="nx-speed-divider" aria-hidden />
        <div className="nx-speed-cell">
          <span className="nx-speed-label"><span className="nx-speed-arrow down">↓</span> {t("overview.download")}</span>
          <span className="nx-speed-value">{formatSpeed(down)}</span>
          {totalDown != null && <span className="nx-speed-total">{formatBytes(totalDown)}</span>}
        </div>
      </div>
    </Card>
  );
};

const XrayCoreCard: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const core = useFetch<CoreStats>(() => api.get("/core"), []);
  const [busy, setBusy] = useState(false);
  usePolling(() => core.reload(), 15000);

  const running = !!core.data?.started;

  const act = async (action: "start" | "stop" | "restart") => {
    if (action === "stop" && !confirm(t("overview.coreStopConfirm"))) return;
    setBusy(true);
    try {
      await api.post(`/core/${action}`);
      toast.push(t("overview.coreActionDone"), "success");
      window.setTimeout(() => core.reload(), 800);
    } catch (e: any) {
      toast.push(e?.message || t("common.error"), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="nx-glass-card">
      <CardHead
        title={t("overview.xrayCore")}
        actions={
          <Pill tone={running ? "ok" : "danger"} dot>
            {running ? t("overview.coreRunning") : t("overview.coreStopped")}
          </Pill>
        }
      />
      <div className="nx-core-row">
        <div className="nx-core-icon" aria-hidden><IcBolt /></div>
        <div className="nx-core-meta">
          <span className="nx-core-version">Xray {core.data?.version ? `v${core.data.version}` : "—"}</span>
          <span className="nx-core-hint">
            {running ? t("overview.coreRunningHint") : (core.data?.startup_error || t("overview.coreStoppedHint"))}
          </span>
        </div>
      </div>
      <div className="nx-core-actions">
        {running ? (
          <Button variant="danger" size="sm" disabled={busy} onClick={() => act("stop")}>
            <span aria-hidden style={{ fontSize: 12 }}>■</span> {t("overview.stop")}
          </Button>
        ) : (
          <Button variant="primary" size="sm" disabled={busy} onClick={() => act("start")}>
            <span aria-hidden style={{ fontSize: 12 }}>▶</span> {t("overview.start")}
          </Button>
        )}
        <Button variant="ghost" size="sm" disabled={busy} onClick={() => act("restart")}>
          <IcRefresh className="nx-ico" /> {t("overview.restart")}
        </Button>
      </div>
    </Card>
  );
};

export const Overview: FC = () => {
  const { t, i18n } = useTranslation();
  const { admin, isEnabled } = useApp();
  const { setOpen } = useCopilot();
  const sys = useFetch<SystemStats>(() => api.get("/system"), []);
  const top = useFetch<TopUser[]>(() => api.get("/analytics/top-users?limit=8"), []);
  const protoUsage = useFetch<ProtocolUsageRow[]>(() => api.get("/analytics/usage-by-protocol"), []);
  const nodes = useFetch<{ id: number; status: string }[]>(
    () => (admin?.is_sudo ? api.get("/nodes") : Promise.resolve([])),
    [admin?.is_sudo],
  );
  const inbounds = useFetch<Record<string, unknown[]>>(
    () => (admin?.is_sudo ? api.get("/inbounds") : Promise.resolve({})),
    [admin?.is_sudo],
  );
  const nodesUsage = useFetch<{ usages: NodeUsageRow[] }>(
    () => (admin?.is_sudo ? api.get("/analytics/nodes-usage") : Promise.resolve({ usages: [] })),
    [admin?.is_sudo],
  );
  const workspace = useFetch<ResellerWorkspace>(
    () => (admin?.is_sudo ? Promise.resolve(null as unknown as ResellerWorkspace) : api.get("/reseller/workspace")),
    [admin?.is_sudo],
  );
  const mrr = useFetch<MrrSummary>(
    () => (admin?.is_sudo && isEnabled("billing") ? api.get("/billing/mrr?days=30") : Promise.resolve(null as unknown as MrrSummary)),
    [admin?.is_sudo, isEnabled("billing")],
  );
  const ws = workspace.data;
  const [rt, setRt] = useState<RealtimeStats | null>(null);
  const [rtStale, setRtStale] = useState(false);

  usePolling(() => {
    api.get<RealtimeStats>("/analytics/realtime")
      .then((d) => { setRt(d); setRtStale(false); })
      .catch(() => setRtStale(true));
  }, 5000);

  usePolling(() => sys.reload(), 15000);
  useLiveReload(() => {
    top.reload();
    protoUsage.reload();
    nodes.reload();
    inbounds.reload();
    nodesUsage.reload();
    workspace.reload();
    mrr.reload();
  }, 30000);

  const { hasUpdate, check, openUpdateModal } = usePanelUpdate();
  const s = sys.data;

  const connectedNodes = (nodes.data || []).filter((n) => n.status === "connected").length;
  const hasInbounds = Object.values(inbounds.data || {}).some((arr) => arr.length > 0);
  const hasUsers = (s?.total_user ?? 0) > 0;
  const setupDone = connectedNodes > 0 && hasUsers;

  const healthItems = useMemo(() => {
    if (!admin?.is_sudo) return [];
    return [
      {
        id: "nodes",
        ok: connectedNodes > 0,
        label: t("overview.healthNodes"),
        hint: connectedNodes > 0 ? t("overview.healthNodesOk", { n: connectedNodes }) : t("overview.healthNodesNo"),
        to: "/servers?tab=nodes",
      },
      {
        id: "inbounds",
        ok: hasInbounds,
        optional: true,
        label: t("overview.healthInbounds"),
        hint: hasInbounds ? t("overview.healthInboundsOk") : t("overview.healthInboundsNo"),
        to: "/connection?tab=inbounds",
      },
      {
        id: "users",
        ok: hasUsers,
        label: t("overview.healthUsers"),
        hint: hasUsers ? t("overview.healthUsersOk", { n: s?.total_user }) : t("overview.healthUsersNo"),
        to: "/users",
      },
    ];
  }, [admin?.is_sudo, connectedNodes, hasInbounds, hasUsers, s?.total_user, t]);

  return (
    <div className="nx-overview">
      <PageHeader
        title={t("overview.title")}
        subtitle={t("overview.subtitle")}
        actions={admin?.is_sudo ? (
          <Button variant="ghost" onClick={() => setOpen(true)}>✦ {t("overview.openGuide")}</Button>
        ) : undefined}
      />

      {hasUpdate && check && (
        <Callout tone="info" className="compact nx-mb-16">
          {t("system.updatesBehind", {
            from: check.current_version,
            to: check.remote_version,
          })}{" "}
          <button
            type="button"
            className="nx-link-btn"
            style={{ marginInlineStart: 8, fontWeight: 600 }}
            onClick={openUpdateModal}
          >
            {t("system.applyUpdates")} →
          </button>
        </Callout>
      )}

      {!admin?.is_sudo && ws?.wallet_low && (
        <Callout tone="warn" title={t("overview.lowWalletTitle")} className="nx-mb-16">
          {t("overview.lowWalletHint")}
        </Callout>
      )}

      {admin?.is_sudo && healthItems.length > 0 && !setupDone && (
        <div className="nx-mb-20">
          <HealthChecklist items={healthItems} />
        </div>
      )}

      {admin?.is_sudo && !setupDone && (
        <div className="nx-quick-actions nx-mb-20">
          <Link to="/servers?tab=nodes" className="nx-quick-card accent">
            <IcServer className="nx-ico" />
            <span>{t("overview.quickAddServer")}</span>
          </Link>
          <Link to="/connection?tab=inbounds" className="nx-quick-card">
            <span className="nx-quick-ico">⚡</span>
            <span>{t("overview.quickAddInbound")}</span>
          </Link>
          <Link to="/users" className="nx-quick-card ok">
            <IcUsers className="nx-ico" />
            <span>{t("overview.quickAddUser")}</span>
          </Link>
        </div>
      )}

      {admin?.is_sudo && s && (
        <div className="nx-mb-20">
          <SystemVitals
            cpu={s.cpu_usage}
            cpuCores={s.cpu_cores}
            memUsed={s.mem_used}
            memTotal={s.mem_total}
            diskUsed={s.disk_used}
            diskTotal={s.disk_total}
          />
        </div>
      )}

      {admin?.is_sudo && (
        <div className="nx-overview-grid nx-mb-20">
          <OverallSpeedCard
            up={rt?.outgoing_bandwidth_speed ?? s?.outgoing_bandwidth_speed ?? 0}
            down={rt?.incoming_bandwidth_speed ?? s?.incoming_bandwidth_speed ?? 0}
            totalUp={s?.outgoing_bandwidth}
            totalDown={s?.incoming_bandwidth}
            stale={rtStale}
          />
          <XrayCoreCard />
        </div>
      )}

      {sys.loading && !s ? (
        <Card><SkeletonRows rows={2} cols={4} /></Card>
      ) : (
        <div className="nx-kpi-grid">
          <KpiTile
            tone="accent"
            label={t("overview.totalUsers")}
            value={s?.total_user ?? "—"}
            icon={<IcUsers />}
            to="/users"
          />
          <KpiTile
            tone="info"
            label={t("overview.onlineUsers")}
            value={rt?.online_users ?? s?.online_users ?? "—"}
            icon={<IcBolt />}
            sub={<><span className="nx-kpi-live-dot" />{t("users.stats.online")}</>}
          />
          <KpiTile
            tone="ok"
            label={t("overview.activeUsers")}
            value={s?.users_active ?? "—"}
            icon={<IcCheck />}
            sub={s && s.total_user > 0
              ? `${Math.round((s.users_active / s.total_user) * 100)}%`
              : undefined}
          />
          <KpiTile
            tone="warn"
            label={t("overview.inactiveUsers")}
            value={s ? Math.max(0, s.total_user - s.users_active) : "—"}
            icon={<IcAlert />}
            sub={`${s?.users_disabled ?? 0} ${t("users.status.disabled")}`}
          />
          {admin?.is_sudo ? (
            <KpiTile
              tone="accent"
              label={t("overview.nodes")}
              value={rt?.nodes_connected ?? connectedNodes}
              icon={<IcServer />}
              to="/servers?tab=nodes"
            />
          ) : (
            <>
              <KpiTile tone="accent" label={t("overview.myNodes")} value={ws?.nodes_count ?? "—"} icon={<IcServer />} />
              {ws?.wallet_balance != null && (
                <KpiTile tone="info" label={t("billing.wallet")} value={ws.wallet_balance.toLocaleString()} icon={<IcWallet />} />
              )}
            </>
          )}
        </div>
      )}

      <div className="nx-overview-grid nx-mb-20">
        <UptimeCard
          xray={s?.xray_uptime}
          os={s?.os_uptime}
          node={s?.node_uptime}
          showNode={!!admin?.is_sudo && (s?.node_uptime ?? 0) > 0}
        />

        <Card className="nx-glass-card">
          <CardHead title={t("analytics.protocolUsage", "Usage by protocol")} />
          {protoUsage.loading ? (
            <SkeletonRows rows={3} cols={2} />
          ) : protoUsage.error ? (
            <EmptyState title={t("common.error")} desc={protoUsage.error} action={<Button onClick={protoUsage.reload}>{t("common.retry")}</Button>} />
          ) : protoUsage.data?.length ? (
            <RankBars
              data={[...protoUsage.data]
                .sort((a, b) => b.used_traffic - a.used_traffic)
                .map((r) => ({ label: r.protocol.toUpperCase(), value: r.used_traffic }))}
              format={(n) => formatBytes(n, 0)}
            />
          ) : (
            <div className="nx-muted nx-center" style={{ padding: 20 }}>{t("common.noData")}</div>
          )}
        </Card>
      </div>

      {admin?.is_sudo && mrr.data && (
        <Card className="nx-glass-card nx-mb-20">
          <CardHead title={t("overview.mrrTitle")} desc={t("overview.mrrDesc", { days: mrr.data.period_days })} />
          <div className="nx-stat-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" }}>
            <Stat label={t("overview.mrrRevenue")} value={mrr.data.total_revenue.toLocaleString()} icon={<IcWallet className="nx-stat-ico" />} />
            <Stat label={t("overview.mrrFloat")} value={mrr.data.wallet_float.toLocaleString()} />
            <Stat label={t("overview.mrrResellers")} value={String(mrr.data.active_resellers)} />
          </div>
        </Card>
      )}

      <div className="nx-overview-grid">
        {admin?.is_sudo && nodesUsage.data?.usages?.length ? (
          <Card className="nx-glass-card">
            <CardHead title={t("overview.nodesUsage")} />
            <RankBars
              data={nodesUsage.data.usages.map((n) => ({
                label: n.node_name,
                value: n.uplink + n.downlink,
                sub: `↑ ${formatBytes(n.uplink, 0)} · ↓ ${formatBytes(n.downlink, 0)}`,
              }))}
              format={(v) => formatBytes(v, 0)}
            />
          </Card>
        ) : null}

        <Card className="nx-glass-card">
          <CardHead title={t("overview.topUsers")} actions={<Link to="/users" className="nx-link-btn" style={{ fontSize: 12, fontWeight: 600 }}>{t("common.viewAll", "View all")} →</Link>} />
          {top.loading ? (
            <SkeletonRows rows={3} cols={2} />
          ) : top.error ? (
            <EmptyState title={t("common.error")} desc={top.error} action={<Button onClick={top.reload}>{t("common.retry")}</Button>} />
          ) : top.data?.length ? (
            <RankBars
              data={top.data.map((u) => ({ label: u.username, value: u.used_traffic }))}
              format={(n) => formatBytes(n, 0)}
            />
          ) : (
            <div className="nx-muted nx-center" style={{ padding: 20 }}>{t("common.noData")}</div>
          )}
        </Card>
      </div>

      <div className="nx-row nx-faint" style={{ marginTop: 16, fontSize: 12, justifyContent: "flex-end" }}>
        {t("overview.version")} {s?.version} · {new Intl.DateTimeFormat(i18n.language).format(new Date())}
      </div>
    </div>
  );
};
