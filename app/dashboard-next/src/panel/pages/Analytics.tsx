import { FC, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { TopUser } from "../api/types";
import { useApp } from "../context/AppContext";
import { useFetch } from "../lib/useFetch";
import { formatBytes, statusTone } from "../lib/format";
import { PageHeader } from "../components/Shell";
import { Button, Callout, Card, CardHead, EmptyState, Field, Pill, Select, SkeletonRows, useToast } from "../components/ui";
import { RankBars } from "../components/charts";

export const Analytics: FC<{ embedded?: boolean }> = ({ embedded }) => {
  const { t } = useTranslation();
  const { admin, isEnabled } = useApp();
  const top = useFetch<TopUser[]>(() => api.get("/analytics/top-users?limit=15"), []);

  return (
    <div className="nx-page">
      {!embedded && <PageHeader title={t("analytics.title")} subtitle={t("analytics.subtitle")} description={t("analytics.description")} />}

      <Card className="nx-mb-20">
        <CardHead title={t("analytics.topUsers")} />
        {top.loading ? <SkeletonRows rows={3} cols={2} />
          : top.error ? <EmptyState title={t("common.error")} desc={top.error} action={<Button onClick={top.reload}>{t("common.retry")}</Button>} />
          : !top.data?.length ? <EmptyState title={t("common.noData")} />
          : (
            <>
              <RankBars data={top.data.slice(0, 10).map((u) => ({ label: u.username, value: u.used_traffic }))} format={(n) => formatBytes(n, 0)} />
              <div className="nx-table-wrap nx-table-inset">
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

      {admin?.is_sudo && isEnabled("smart_routing") && <SmartRoutingCard />}
      {admin?.is_sudo && <IntelligenceCard enabled={isEnabled("traffic_intelligence")} />}
    </div>
  );
};

type RoutedNode = { id: number; name: string; region?: string | null; latency_ms?: number | null; status: string };

const SmartRoutingCard: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const [strategies, setStrategies] = useState<string[]>([]);
  const [strategy, setStrategy] = useState("");
  const [nodes, setNodes] = useState<RoutedNode[]>([]);
  const [busy, setBusy] = useState(false);

  const [strategiesError, setStrategiesError] = useState("");
  useEffect(() => {
    api.get<string[]>("/routing/strategies").then((s) => {
      setStrategies(s);
      if (s.length) setStrategy(s[0]);
      setStrategiesError("");
    }).catch((e: any) => setStrategiesError(e?.message || "error"));
  }, []);

  const load = async () => {
    setBusy(true);
    try {
      const q = strategy ? `?strategy=${encodeURIComponent(strategy)}&limit=20` : "?limit=20";
      setNodes(await api.get(`/routing/nodes${q}`));
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="nx-mb-20">
      <CardHead title={t("analytics.smartRouting")} actions={
        <Button variant="primary" size="sm" disabled={busy} onClick={load}>{t("analytics.loadNodes")}</Button>
      } />
      <div className="nx-row" style={{ gap: 12, marginBottom: 12 }}>
        <Field label={t("analytics.strategy")}>
          <Select value={strategy} onChange={(e: any) => setStrategy(e.target.value)} style={{ minWidth: 180 }}>
            {strategies.map((s) => <option key={s} value={s}>{s}</option>)}
          </Select>
        </Field>
      </div>
      {strategiesError ? <Callout tone="warn" title={t("common.error")}>{strategiesError}</Callout> : null}
      {!nodes.length ? <div className="nx-faint" style={{ fontSize: 13 }}>{t("analytics.routingHint")}</div>
        : (
          <div className="nx-table-wrap">
            <table className="nx-table">
              <thead><tr><th>#</th><th>{t("common.name")}</th><th>{t("infra.region")}</th><th>{t("infra.latency")}</th><th>{t("common.status")}</th></tr></thead>
              <tbody>
                {nodes.map((n, i) => (
                  <tr key={n.id}>
                    <td className="nx-faint">{i + 1}</td>
                    <td style={{ fontWeight: 600 }}>{n.name}</td>
                    <td>{n.region || "—"}</td>
                    <td>{n.latency_ms != null ? `${n.latency_ms.toFixed(0)} ms` : "—"}</td>
                    <td><Pill tone={statusTone(n.status)} dot>{n.status}</Pill></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
    </Card>
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
        <div className="nx-muted nx-center" style={{ padding: 20 }}>{t("analytics.runHint")}</div>
      ) : (
        <div className="nx-intel-grid">
          {groups.map((g) => {
            const items = Array.isArray(data[g.key]) ? data[g.key] : data[g.key] ? [data[g.key]] : [];
            return (
              <div key={g.key} className="nx-intel-card">
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
