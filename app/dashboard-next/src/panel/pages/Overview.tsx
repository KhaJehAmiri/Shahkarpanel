import { FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { RealtimeStats, SystemStats, TopUser } from "../api/types";
import { useApp } from "../context/AppContext";
import { useCopilot } from "../copilot/CopilotContext";
import { useFetch, usePolling } from "../lib/useFetch";
import { formatBytes, formatSpeed } from "../lib/format";
import { PageHeader } from "../components/Shell";
import { PathCard } from "../components/PathCard";
import { Card, CardHead, Stat, UsageBar, SkeletonRows, Pill, Callout, Button } from "../components/ui";
import { BarChart, Donut } from "../components/charts";
import { IcUsers, IcServer, IcBolt, IcChart, IcDownload, IcInbound, IcShield, IcLink } from "../components/icons";

type NodeUsageRow = { node_id: number | null; node_name: string; uplink: number; downlink: number };

export const Overview: FC = () => {
  const { t, i18n } = useTranslation();
  const { admin } = useApp();
  const { setOpen } = useCopilot();
  const sys = useFetch<SystemStats>(() => api.get("/system"), []);
  const top = useFetch<TopUser[]>(() => api.get("/analytics/top-users?limit=8"), []);
  const nodesUsage = useFetch<{ usages: NodeUsageRow[] }>(
    () => (admin?.is_sudo ? api.get("/analytics/nodes-usage") : Promise.resolve({ usages: [] })),
    [admin?.is_sudo],
  );
  const [rt, setRt] = useState<RealtimeStats | null>(null);

  usePolling(() => {
    api.get<RealtimeStats>("/analytics/realtime").then(setRt).catch(() => {});
  }, 5000);

  const s = sys.data;
  const memPct = s ? (s.mem_used / s.mem_total) * 100 : 0;
  const noVpnUsers = (s?.users_active ?? 0) === 0 && (rt?.online_users ?? s?.online_users ?? 0) === 0;
  const bwSource = rt?.bandwidth_source ?? s?.bandwidth_source ?? "nic";

  return (
    <div>
      <PageHeader
        title={t("overview.title")}
        subtitle={t("overview.subtitle")}
        description={t("overview.description")}
        actions={admin?.is_sudo ? (
          <Button variant="ghost" onClick={() => setOpen(true)}>✦ {t("overview.openGuide")}</Button>
        ) : undefined}
      />

      {admin?.is_sudo && (
        <div style={{ marginBottom: 20 }}>
          <div className="nx-muted" style={{ fontSize: 12, fontWeight: 600, marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            {t("overview.pickPath")}
          </div>
          <div className="nx-path-grid">
            <PathCard
              icon={<IcInbound className="nx-ico" />}
              title={t("overview.pathProxy")}
              steps={t("overview.pathProxySteps")}
              action={t("overview.pathStart")}
              to="/inbounds"
              tone="accent"
            />
            <PathCard
              icon={<IcShield className="nx-ico" />}
              title={t("overview.pathWg")}
              steps={t("overview.pathWgSteps")}
              action={t("overview.pathStart")}
              to="/wireguard"
              tone="ok"
            />
            <PathCard
              icon={<IcLink className="nx-ico" />}
              title={t("overview.pathTunnel")}
              steps={t("overview.pathTunnelSteps")}
              action={t("overview.pathStart")}
              to="/tunnels"
              tone="info"
            />
          </div>
        </div>
      )}

      {sys.loading && !s ? (
        <Card><SkeletonRows rows={2} cols={4} /></Card>
      ) : (
        <div className="nx-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))" }}>
          <Stat label={t("overview.totalUsers")} value={s?.total_user ?? "—"} icon={<IcUsers className="nx-stat-ico" />}
            sub={<><Pill tone="ok" dot>{s?.users_active ?? 0} {t("overview.activeUsers")}</Pill></>} />
          <Stat label={t("overview.onlineUsers")} value={s?.online_users ?? "—"} icon={<IcBolt className="nx-stat-ico" />} />
          <Stat label={t("overview.nodes")} value={rt?.nodes_connected ?? "—"} icon={<IcServer className="nx-stat-ico" />} />
          <Stat label={t("overview.cpu")} value={`${s?.cpu_usage?.toFixed(0) ?? 0}%`} icon={<IcChart className="nx-stat-ico" />}
            sub={t("overview.cores", { n: s?.cpu_cores ?? 0 })} />
          <Stat label={t("overview.memory")} value={formatBytes(s?.mem_used)}
            sub={<div style={{ marginTop: 6 }}><UsageBar pct={memPct} /></div>} />
        </div>
      )}

      <div className="nx-grid" style={{ gridTemplateColumns: "1fr 1fr", marginTop: 16 }}>
        <Card>
          <CardHead
            title={t("overview.liveThroughput")}
            actions={
              <Pill tone="default">
                {bwSource === "xray" ? t("overview.bwXray") : t("overview.bwNic")}
              </Pill>
            }
          />
          {noVpnUsers && (rt?.incoming_bandwidth_speed || rt?.outgoing_bandwidth_speed) ? (
            <Callout tone="info" title={t("overview.noActiveUsersTitle")}>
              {t("overview.noActiveUsersBwHint")}
            </Callout>
          ) : null}
          <div className="nx-row" style={{ gap: 28 }}>
            <Stat label={`↓ ${t("overview.download")}`} value={formatSpeed(rt?.incoming_bandwidth_speed ?? 0)} />
            <Stat label={`↑ ${t("overview.upload")}`} value={formatSpeed(rt?.outgoing_bandwidth_speed ?? 0)} />
          </div>
          <div style={{ marginTop: 16 }}>
            <div className="nx-muted" style={{ fontSize: 12, marginBottom: 10 }}>{t("overview.totalTraffic")}</div>
            <div className="nx-row" style={{ gap: 24 }}>
              <div><IcDownload className="nx-ico" style={{ color: "var(--nx-accent)" }} /> {t("overview.incoming")}: <b>{formatBytes(s?.incoming_bandwidth)}</b></div>
              <div>{t("overview.outgoing")}: <b>{formatBytes(s?.outgoing_bandwidth)}</b></div>
            </div>
          </div>
        </Card>

        <Card>
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

      {admin?.is_sudo && nodesUsage.data?.usages?.length ? (
        <Card style={{ marginTop: 16 }}>
          <CardHead title={t("overview.nodesUsage")} />
          <BarChart
            data={nodesUsage.data.usages.map((n) => ({
              label: n.node_name,
              value: n.uplink + n.downlink,
            }))}
            format={(v) => formatBytes(v, 0)}
          />
        </Card>
      ) : null}

      <Card style={{ marginTop: 16 }}>
        <CardHead title={t("overview.topUsers")} />
        {top.loading ? (
          <SkeletonRows rows={3} cols={2} />
        ) : top.data && top.data.length ? (
          <BarChart
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
