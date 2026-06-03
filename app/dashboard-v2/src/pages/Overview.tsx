import { FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { RealtimeStats, SystemStats, TopUser } from "../api/types";
import { useFetch, usePolling } from "../lib/useFetch";
import { formatBytes, formatSpeed } from "../lib/format";
import { PageHeader } from "../components/Shell";
import { Card, CardHead, Stat, UsageBar, SkeletonRows, Pill } from "../components/ui";
import { BarChart, Donut } from "../components/charts";
import { IcUsers, IcServer, IcBolt, IcChart, IcDownload } from "../components/icons";

export const Overview: FC = () => {
  const { t, i18n } = useTranslation();
  const sys = useFetch<SystemStats>(() => api.get("/system"), []);
  const top = useFetch<TopUser[]>(() => api.get("/analytics/top-users?limit=8"), []);
  const [rt, setRt] = useState<RealtimeStats | null>(null);

  usePolling(() => {
    api.get<RealtimeStats>("/analytics/realtime").then(setRt).catch(() => {});
  }, 5000);

  const s = sys.data;
  const memPct = s ? (s.mem_used / s.mem_total) * 100 : 0;

  return (
    <div>
      <PageHeader title={t("overview.title")} subtitle={t("overview.subtitle")} />

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
          <CardHead title={t("overview.liveThroughput")} actions={<Pill tone="accent" dot>live</Pill>} />
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
