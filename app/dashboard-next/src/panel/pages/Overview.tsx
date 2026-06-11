import { FC, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { MrrSummary, RealtimeStats, ResellerWorkspace, SystemStats, TopUser } from "../api/types";
import { usePanelUpdate } from "../context/UpdateContext";
import { useApp } from "../context/AppContext";
import { useCopilot } from "../copilot/CopilotContext";
import { useFetch, useLiveReload, usePolling } from "../lib/useFetch";
import { formatBytes, formatSpeed } from "../lib/format";
import { PageHeader } from "../components/Shell";
import { HealthChecklist } from "../components/HealthChecklist";
import { SystemVitals } from "../components/viz/SystemVitals";
import { Card, CardHead, Stat, SkeletonRows, Pill, Callout, Button, EmptyState } from "../components/ui";
import { Donut, RankBars, Sparkline } from "../components/charts";
import { useMetricHistory } from "../lib/useMetricHistory";
import { IcUsers, IcServer, IcBolt, IcDownload, IcWallet } from "../components/icons";

type NodeUsageRow = { node_id: number | null; node_name: string; uplink: number; downlink: number };

export const Overview: FC = () => {
  const { t, i18n } = useTranslation();
  const { admin, isEnabled } = useApp();
  const { setOpen } = useCopilot();
  const sys = useFetch<SystemStats>(() => api.get("/system"), []);
  const top = useFetch<TopUser[]>(() => api.get("/analytics/top-users?limit=8"), []);
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
    nodes.reload();
    inbounds.reload();
    nodesUsage.reload();
    workspace.reload();
    mrr.reload();
  }, 30000);

  const { hasUpdate, check, openUpdateModal } = usePanelUpdate();
  const s = sys.data;
  const bwSource = rt?.bandwidth_source ?? s?.bandwidth_source ?? "nic";
  const downHist = useMetricHistory(rt?.incoming_bandwidth_speed ?? 0);
  const upHist = useMetricHistory(rt?.outgoing_bandwidth_speed ?? 0);

  const connectedNodes = (nodes.data || []).filter((n) => n.status === "connected").length;
  const hasInbounds = Object.values(inbounds.data || {}).some((arr) => arr.length > 0);
  const hasUsers = (s?.total_user ?? 0) > 0;
  const setupDone = connectedNodes > 0 && hasInbounds && hasUsers;

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

      {admin?.is_sudo && healthItems.length > 0 && (
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
          <SystemVitals cpu={s.cpu_usage} cpuCores={s.cpu_cores} memUsed={s.mem_used} memTotal={s.mem_total} />
        </div>
      )}

      {sys.loading && !s ? (
        <Card><SkeletonRows rows={2} cols={4} /></Card>
      ) : (
        <div className="nx-stat-grid">
          <div className="nx-glass-card nx-stat-tile">
            <Stat label={t("overview.totalUsers")} value={s?.total_user ?? "—"} icon={<IcUsers className="nx-stat-ico" />}
              sub={<Pill tone="ok" dot>{s?.users_active ?? 0} {t("overview.activeUsers")}</Pill>} />
          </div>
          <div className="nx-glass-card nx-stat-tile">
            <Stat label={t("overview.onlineUsers")} value={rt?.online_users ?? s?.online_users ?? "—"} icon={<IcBolt className="nx-stat-ico" />} />
          </div>
          {admin?.is_sudo ? (
            <div className="nx-glass-card nx-stat-tile">
              <Stat label={t("overview.nodes")} value={rt?.nodes_connected ?? connectedNodes} icon={<IcServer className="nx-stat-ico" />} />
            </div>
          ) : (
            <>
              <div className="nx-glass-card nx-stat-tile">
                <Stat label={t("overview.myNodes")} value={ws?.nodes_count ?? "—"} icon={<IcServer className="nx-stat-ico" />} />
              </div>
              {ws?.wallet_balance != null && (
                <div className="nx-glass-card nx-stat-tile">
                  <Stat label={t("billing.wallet")} value={ws.wallet_balance.toLocaleString()} icon={<IcWallet className="nx-stat-ico" />} />
                </div>
              )}
            </>
          )}
        </div>
      )}

      <div className="nx-overview-grid nx-mb-20">
        <Card className="nx-glass-card">
          <CardHead
            title={t("overview.liveThroughput")}
            actions={rtStale
              ? <Pill tone="warn" dot>{t("overview.liveStale")}</Pill>
              : <Pill tone="default">{bwSource === "xray" ? t("overview.bwXray") : t("overview.bwNic")}</Pill>}
          />
          <div className="nx-throughput-row">
            <div className="nx-throughput-stat">
              <span className="nx-throughput-label">↓ {t("overview.download")}</span>
              <span className="nx-throughput-value">{formatSpeed(rt?.incoming_bandwidth_speed ?? 0)}</span>
              <Sparkline data={downHist.length ? downHist : [0]} height={40} />
            </div>
            <div className="nx-throughput-stat">
              <span className="nx-throughput-label">↑ {t("overview.upload")}</span>
              <span className="nx-throughput-value">{formatSpeed(rt?.outgoing_bandwidth_speed ?? 0)}</span>
              <Sparkline data={upHist.length ? upHist : [0]} height={40} color="var(--nx-info)" />
            </div>
          </div>
          <div className="nx-faint" style={{ fontSize: 12, marginTop: 14 }}>
            <IcDownload className="nx-ico" style={{ color: "var(--nx-accent)" }} /> {t("overview.incoming")}: <b>{formatBytes(s?.incoming_bandwidth)}</b>
            {" · "}{t("overview.outgoing")}: <b>{formatBytes(s?.outgoing_bandwidth)}</b>
          </div>
        </Card>

        <Card className="nx-glass-card">
          <CardHead title={t("overview.usersByStatus")} />
          {s && (
            <Donut
              segments={[
                { label: t("users.status.active"), value: s.users_active, color: "var(--nx-ok)" },
                { label: t("users.status.on_hold"), value: s.users_on_hold, color: "var(--nx-info)" },
                { label: t("users.status.limited"), value: s.users_limited, color: "var(--nx-warn)" },
                { label: t("users.status.expired"), value: s.users_expired, color: "#a78bfa" },
                { label: t("users.status.disabled"), value: s.users_disabled, color: "var(--nx-danger)" },
              ]}
            />
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

      {admin?.is_sudo && nodesUsage.data?.usages?.length ? (
        <Card className="nx-glass-card nx-mb-20">
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
        <CardHead title={t("overview.topUsers")} />
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

      <div className="nx-row nx-faint" style={{ marginTop: 16, fontSize: 12, justifyContent: "flex-end" }}>
        {t("overview.version")} {s?.version} · {new Intl.DateTimeFormat(i18n.language).format(new Date())}
      </div>
    </div>
  );
};
