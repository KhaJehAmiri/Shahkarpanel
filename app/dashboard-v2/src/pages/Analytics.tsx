import { FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { TopUser } from "../api/types";
import { useApp } from "../context/AppContext";
import { useFetch } from "../lib/useFetch";
import { formatBytes, statusTone } from "../lib/format";
import { PageHeader } from "../components/Shell";
import { Button, Callout, Card, CardHead, EmptyState, Pill, SkeletonRows, useToast } from "../components/ui";
import { BarChart } from "../components/charts";

export const Analytics: FC = () => {
  const { t } = useTranslation();
  const { admin, isEnabled } = useApp();
  const top = useFetch<TopUser[]>(() => api.get("/analytics/top-users?limit=15"), []);

  return (
    <div>
      <PageHeader title={t("analytics.title")} subtitle={t("analytics.subtitle")} />

      <Card style={{ marginBottom: 16 }}>
        <CardHead title={t("analytics.topUsers")} />
        {top.loading ? <SkeletonRows rows={3} cols={2} />
          : !top.data?.length ? <EmptyState title={t("common.noData")} />
          : (
            <>
              <BarChart data={top.data.slice(0, 10).map((u) => ({ label: u.username, value: u.used_traffic }))} format={(n) => formatBytes(n, 0)} />
              <div className="nx-table-wrap" style={{ marginTop: 16 }}>
                <table className="nx-table">
                  <thead><tr><th>#</th><th>{t("common.username")}</th><th>{t("users.used")}</th><th>{t("common.status")}</th></tr></thead>
                  <tbody>
                    {top.data.map((u, i) => (
                      <tr key={u.username}>
                        <td className="nx-faint">{i + 1}</td>
                        <td style={{ fontWeight: 600 }}>{u.username}</td>
                        <td>{formatBytes(u.used_traffic)}</td>
                        <td><Pill tone={statusTone(u.status)} dot>{t(`users.status.${u.status}`, u.status)}</Pill></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
      </Card>

      {admin?.is_sudo && <IntelligenceCard enabled={isEnabled("traffic_intelligence")} />}
    </div>
  );
};

const IntelligenceCard: FC<{ enabled: boolean }> = ({ enabled }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [data, setData] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try { setData(await api.get("/intelligence/summary")); }
    catch (e: any) { toast.push(e.status === 404 ? t("analytics.intelligenceDisabled") : e.message, "error"); }
    finally { setBusy(false); }
  };

  if (!enabled) return <Callout tone="warn" title={t("analytics.intelligence")}>{t("analytics.intelligenceDisabled")}</Callout>;

  const groups: { key: string; label: string }[] = [
    { key: "heavy_users", label: t("analytics.heavyUsers") },
    { key: "exhaustion_risk", label: t("analytics.exhaustionRisk") },
    { key: "node_risk", label: t("analytics.nodeRisk") },
  ];

  return (
    <Card>
      <CardHead title={t("analytics.intelligence")} actions={<Button variant="primary" onClick={run} disabled={busy}>{t("analytics.run")}</Button>} />
      {!data ? (
        <div className="nx-muted nx-center" style={{ padding: 20 }}>{t("analytics.run")}</div>
      ) : (
        <div className="nx-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
          {groups.map((g) => {
            const items = Array.isArray(data[g.key]) ? data[g.key] : data[g.key] ? [data[g.key]] : [];
            return (
              <div key={g.key} className="nx-card" style={{ background: "var(--nx-surface-2)" }}>
                <div className="nx-row" style={{ justifyContent: "space-between", marginBottom: 10 }}>
                  <b>{g.label}</b><Pill tone={items.length ? "warn" : "ok"}>{items.length}</Pill>
                </div>
                {!items.length ? <div className="nx-faint" style={{ fontSize: 12 }}>{t("analytics.noFindings")}</div>
                  : <div className="nx-stack" style={{ gap: 6 }}>
                      {items.slice(0, 6).map((it: any, i: number) => (
                        <div key={i} className="nx-code" style={{ fontSize: 11, padding: "4px 8px", wordBreak: "break-all" }}>
                          {it.username || it.name || it.node_name || JSON.stringify(it).slice(0, 80)}
                        </div>
                      ))}
                    </div>}
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
};
