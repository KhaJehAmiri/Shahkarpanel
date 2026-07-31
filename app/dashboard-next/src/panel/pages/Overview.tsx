import { FC, ReactNode, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { CoreStats, GatewayIncome, MrrSummary, RealtimeStats, ResellerWorkspace, SystemStats, TopUser } from "../api/types";
import { usePanelUpdate } from "../context/UpdateContext";
import { useApp } from "../context/AppContext";
import { useCopilot } from "../copilot/CopilotContext";
import { useFetch, useLiveReload, usePolling } from "../lib/useFetch";
import { formatBytes, formatCompactAmount, formatSpeed, usagePct } from "../lib/format";
import { PageHeader } from "../components/Shell";
import { HealthChecklist } from "../components/HealthChecklist";
import { SystemVitals } from "../components/viz/SystemVitals";
import { LiveValue } from "../components/viz/LiveValue";
import { Card, SkeletonRows, Callout, Button, EmptyState, useToast } from "../components/ui";
import { RankBars, Sparkline } from "../components/charts";
import { IcUsers, IcServer, IcBolt, IcRefresh, IcMonitor, IcDownload } from "../components/icons";
import { BackupRestoreModal } from "../components/BackupRestoreModal";

type NodeUsageRow = { node_id: number | null; node_name: string; uplink: number; downlink: number };
type ProtocolUsageRow = { protocol: string; used_traffic: number };
type PayPeriod = "today" | "yesterday" | "week" | "total";

const PROVIDER_LABEL: Record<string, string> = {
  centralpay: "CentralPay",
  stripe: "Stripe",
  demo: "Demo",
  card: "Card",
};

const PaymentPulse: FC<{
  income: GatewayIncome;
  methods: string[];
  isSudo: boolean;
}> = ({ income, methods, isSudo }) => {
  const { t } = useTranslation();
  const [period, setPeriod] = useState<PayPeriod>("today");
  const cur = income.currency_label || "";

  const amount = income[period] ?? 0;
  const count =
    period === "today" ? (income.today_count ?? 0)
    : period === "yesterday" ? (income.yesterday_count ?? 0)
    : period === "week" ? (income.week_count ?? 0)
    : income.payments_count;

  const byKind =
    period === "today" ? (income.today_by_kind || {})
    : period === "yesterday" ? (income.yesterday_by_kind || {})
    : period === "week" ? (income.week_by_kind || {})
    : (income.total_by_kind || income.by_kind || {});

  const portalAmt = (byKind.portal_renew || 0) + (byKind.portal_purchase || 0);
  const topupAmt = byKind.topup || 0;

  const delta = period === "today" ? amount - (income.yesterday || 0) : null;
  const deltaPct =
    delta != null && income.yesterday
      ? Math.round((delta / Math.abs(income.yesterday)) * 100)
      : null;

  const periods: { id: PayPeriod; label: string }[] = [
    { id: "today", label: t("overview.payToday") },
    { id: "yesterday", label: t("overview.payYesterday") },
    { id: "week", label: t("overview.payWeek") },
    { id: "total", label: t("overview.payTotal") },
  ];

  const topResellers = useMemo(() => {
    if (!isSudo) return [];
    return [...(income.resellers || [])]
      .filter((r) => !r.is_sudo)
      .sort((a, b) => (b[period] || 0) - (a[period] || 0))
      .slice(0, 3)
      .filter((r) => (r[period] || 0) > 0);
  }, [income.resellers, isSudo, period]);

  const fmt = (n: number) => {
    const body = formatCompactAmount(n);
    return cur ? `${body} ${cur}` : body;
  };

  return (
    <div className="sk-pay-pulse">
      <div className="sk-pay-pulse-head">
        <div className="sk-pay-pulse-title-row">
          <span className="sk-pay-pulse-title">{t("overview.payTitle")}</span>
          <span className="sk-pay-pulse-sub">{t("overview.paySubtitle")}</span>
        </div>
        <div className="sk-pay-pulse-tools">
          <div className="sk-pay-period" role="tablist" aria-label={t("overview.payTitle")}>
            {periods.map((p) => (
              <button
                key={p.id}
                type="button"
                role="tab"
                aria-selected={period === p.id}
                className={`sk-pay-period-btn${period === p.id ? " is-on" : ""}`}
                onClick={() => setPeriod(p.id)}
              >
                {p.label}
              </button>
            ))}
          </div>
          <Link to="/billing?billingTab=income" className="sk-pay-pulse-link">
            {t("overview.payOpen")}
          </Link>
        </div>
      </div>

      <div className="sk-pay-pulse-grid">
        <article className="sk-pay-tile sk-pay-tile-hero">
          <span className="sk-pay-tile-label">{t("overview.payIncome")}</span>
          <LiveValue className="sk-pay-tile-value" value={amount} format={fmt} />
          {delta != null ? (
            <span className={`sk-pay-delta${delta > 0 ? " is-up" : delta < 0 ? " is-down" : ""}`}>
              {delta === 0
                ? t("overview.payFlat")
                : t("overview.payVsYesterday", {
                    amount: `${delta > 0 ? "+" : ""}${formatCompactAmount(delta)}`,
                    pct: deltaPct != null ? `${deltaPct > 0 ? "+" : ""}${deltaPct}%` : "",
                  })}
            </span>
          ) : (
            <span className="sk-pay-delta">{t("overview.payOrdersCount", { n: count })}</span>
          )}
        </article>

        <article className="sk-pay-tile">
          <span className="sk-pay-tile-label">{t("overview.payOrders")}</span>
          <LiveValue className="sk-pay-tile-value" value={count} />
          <span className="sk-pay-delta">{t("overview.payCompleted")}</span>
        </article>

        <article className="sk-pay-tile">
          <span className="sk-pay-tile-label">{t("overview.payPortal")}</span>
          <LiveValue className="sk-pay-tile-value" value={portalAmt} format={fmt} />
          <span className="sk-pay-delta">{t("overview.payPortalHint")}</span>
        </article>

        <article className="sk-pay-tile">
          <span className="sk-pay-tile-label">{t("overview.payTopup")}</span>
          <LiveValue className="sk-pay-tile-value" value={topupAmt} format={fmt} />
          <span className="sk-pay-delta">{t("overview.payTopupHint")}</span>
        </article>
      </div>

      <div className="sk-pay-pulse-foot">
        <div className="sk-pay-methods">
          <span className="sk-pay-methods-label">{t("overview.payMethods")}</span>
          {methods.map((m) => (
            <span key={m} className={`sk-pay-chip is-${m}`}>
              <i className="sk-pay-chip-dot" aria-hidden />
              {PROVIDER_LABEL[m] || m}
            </span>
          ))}
        </div>
        {topResellers.length > 0 && (
          <div className="sk-pay-leaders">
            <span className="sk-pay-methods-label">{t("overview.payLeaders")}</span>
            {topResellers.map((r, i) => (
              <span key={r.admin_id} className="sk-pay-leader">
                <em>{i + 1}</em>
                <b>{r.username}</b>
                <span>{fmt(r[period] || 0)}</span>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

const Section: FC<{ title?: string; action?: ReactNode; children: ReactNode; className?: string }> = ({
  title,
  action,
  children,
  className,
}) => (
  <section className={`sk-home-section${className ? ` ${className}` : ""}`}>
    {(title || action) && (
      <div className="sk-home-section-head">
        {title ? <h2 className="sk-home-section-title">{title}</h2> : <span />}
        {action}
      </div>
    )}
    {children}
  </section>
);

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

function useSeries(value: number, maxPoints = 28): number[] {
  const [series, setSeries] = useState<number[]>(() => Array.from({ length: 8 }, () => value));
  useEffect(() => {
    setSeries((prev) => [...prev.slice(-(maxPoints - 1)), Math.max(0, value)]);
  }, [value, maxPoints]);
  return series;
}

const ActivityBars: FC<{ level: number; tone?: "up" | "down" }> = ({ level, tone = "up" }) => {
  const bars = 18;
  const intensity = Math.min(1, Math.log10(Math.max(level, 1) + 1) / 8);
  return (
    <div className={`sk-activity ${tone}`} aria-hidden>
      {Array.from({ length: bars }, (_, i) => {
        const wave = 0.35 + 0.65 * Math.abs(Math.sin((i / bars) * Math.PI * 2.2 + intensity * 4));
        const h = Math.max(12, Math.round((20 + intensity * 80) * wave));
        return (
          <span
            key={i}
            className="sk-activity-bar"
            style={{ height: `${h}%`, animationDelay: `${i * 45}ms` }}
          />
        );
      })}
    </div>
  );
};

const KpiTile: FC<{
  label: string;
  value: number | null | undefined;
  sub?: ReactNode;
  to?: string;
  live?: boolean;
}> = ({ label, value, sub, to, live }) => {
  const body = (
    <>
      <span className="sk-kpi-label">
        {live ? <span className="sk-kpi-live-dot" aria-hidden /> : null}
        {label}
      </span>
      <LiveValue className="sk-kpi-value" value={value} format={(n) => Math.round(n).toLocaleString()} />
      {sub ? <span className="sk-kpi-sub">{sub}</span> : null}
    </>
  );
  const cls = `sk-kpi${to ? " sk-kpi-link" : ""}${live ? " is-live" : ""}`;
  return to ? <Link to={to} className={cls}>{body}</Link> : <div className={cls}>{body}</div>;
};

const PACKAGE_BUY_HREF = "/billing?billingTab=packages";

const ResellerCommerceStrip: FC<{ ws: ResellerWorkspace }> = ({ ws }) => {
  const { t } = useTranslation();
  const used = ws.users_usage ?? 0;
  const cap = ws.max_total_traffic ?? null;
  const remaining = cap != null
    ? Math.max(0, (ws.traffic_remaining ?? (cap - used)))
    : null;
  const pct = usagePct(used, cap);
  const currency = (ws.currency_label || "").trim();
  const pending = ws.pending_usage_cost ?? 0;
  const balance = ws.wallet_balance ?? 0;
  const prepaid = ws.prepaid_traffic_remaining ?? 0;
  const packageEmpty = prepaid <= 0;

  return (
    <div className="sk-commerce-strip">
      <article className="sk-commerce-card sk-commerce-wallet">
        <header className="sk-commerce-card-head">
          <span className="sk-commerce-eyebrow">{t("billing.wallet")}</span>
          {ws.wallet_blocked ? (
            <span className="sk-commerce-badge is-danger">{t("overview.walletBlockedBadge")}</span>
          ) : ws.wallet_low ? (
            <span className="sk-commerce-badge is-warn">{t("overview.lowWalletBadge")}</span>
          ) : (
            <span className="sk-commerce-badge is-ok">{t("overview.walletOkBadge")}</span>
          )}
        </header>
        <div className="sk-commerce-balance">
          <strong title={balance.toLocaleString()}>{formatCompactAmount(balance)}</strong>
          {currency ? <span className="sk-commerce-currency">{currency}</span> : null}
        </div>
        <p className="sk-commerce-meta">
          {pending > 0
            ? t("overview.pendingCharge", {
                cost: pending.toLocaleString(),
                currency,
              })
            : ws.last_usage_debit
              ? t("overview.lastDebit", {
                  amount: Math.abs(ws.last_usage_debit.amount).toLocaleString(),
                  currency,
                })
              : ws.usage_rate_per_gb
                ? t("overview.gbRate", {
                    rate: ws.usage_rate_per_gb.toLocaleString(),
                    currency,
                  })
                : t("overview.noPendingCharge")}
        </p>
        <div className="sk-commerce-foot">
          <span>{t("overview.fullBalance")}: {balance.toLocaleString()}{currency ? ` ${currency}` : ""}</span>
          <Link to="/billing" className="sk-commerce-link">{t("overview.openBilling")} →</Link>
        </div>
      </article>

      <article className={`sk-commerce-card sk-commerce-traffic${packageEmpty ? " is-package-empty" : ""}`}>
        <header className="sk-commerce-card-head">
          <span className="sk-commerce-eyebrow">{t("overview.trafficPackage")}</span>
          {packageEmpty ? (
            <span className="sk-commerce-badge is-danger">{t("overview.packageExhaustedBadge")}</span>
          ) : (
            <span className="sk-commerce-badge is-ok">{t("overview.packageActiveBadge")}</span>
          )}
        </header>
        <div className="sk-commerce-balance">
          <strong>{formatBytes(prepaid)}</strong>
          <span className="sk-commerce-currency">{t("overview.packageLeftLabel")}</span>
        </div>
        <div className="sk-commerce-meter" aria-hidden>
          <span style={{ width: packageEmpty ? "100%" : `${Math.max(2, Math.min(100, prepaid > 0 ? 35 : 100))}%` }} />
        </div>
        <p className="sk-commerce-meta">
          {packageEmpty
            ? t("overview.packageExhaustedMeta")
            : t("overview.prepaidRemaining", { remaining: formatBytes(prepaid) })}
          {cap != null
            ? ` · ${t("overview.trafficRemaining", {
                remaining: formatBytes(remaining ?? 0),
                cap: formatBytes(cap),
              })}`
            : ` · ${t("overview.usageTotal", { used: formatBytes(used) })}`}
        </p>
        <div className="sk-commerce-foot">
          {packageEmpty ? (
            <Link to={PACKAGE_BUY_HREF} className="sk-commerce-link" style={{ fontWeight: 700 }}>
              {t("overview.buyPackageCta")} →
            </Link>
          ) : (
            <Link to={PACKAGE_BUY_HREF} className="sk-commerce-link">{t("overview.managePackages")} →</Link>
          )}
          {(ws.pending_usage_bytes ?? 0) > 0 ? (
            <span>
              {t("overview.unbilledCost", {
                cost: (ws.pending_usage_cost ?? 0).toLocaleString(),
                currency,
              })}
            </span>
          ) : null}
        </div>
      </article>
    </div>
  );
};

const LiveHero: FC<{
  up: number;
  down: number;
  totalUp?: number;
  totalDown?: number;
  stale?: boolean;
  xray?: number;
  os?: number;
}> = ({ up, down, totalUp, totalDown, stale, xray, os }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const core = useFetch<CoreStats>(() => api.get("/core"), []);
  const [busy, setBusy] = useState(false);
  usePolling(() => core.reload(), 15000);
  const running = !!core.data?.started;
  const upSeries = useSeries(up);
  const downSeries = useSeries(down);

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
    <div className={`sk-live-hero${stale ? " is-stale" : ""}${running ? " is-running" : " is-stopped"}`}>
      <div className="sk-live-hero-glow" aria-hidden />
      <div className="sk-live-hero-top">
        <div className="sk-live-badge">
          <span className={`sk-live-pulse${stale ? " warn" : ""}`} />
          {stale ? t("overview.liveStale") : t("overview.live")}
        </div>
        <div className={`sk-core-chip${running ? " ok" : " danger"}`}>
          <span className="sk-core-chip-dot" />
          {running ? t("overview.coreRunning") : t("overview.coreStopped")}
          <span className="sk-core-chip-ver">Xray {core.data?.version ? `v${core.data.version}` : "—"}</span>
        </div>
      </div>

      <div className="sk-live-hero-grid">
        <div className="sk-live-stream">
          <div className="sk-live-stream-head">
            <span className="sk-speed-arrow up">↑</span>
            <span>{t("overview.upload")}</span>
          </div>
          <div className="sk-live-stream-value">{formatSpeed(up)}</div>
          {totalUp != null && <div className="sk-live-stream-total">{formatBytes(totalUp)} total</div>}
          <ActivityBars level={up} tone="up" />
          <Sparkline data={upSeries} height={42} color="var(--sk-info)" />
        </div>

        <div className="sk-live-stream">
          <div className="sk-live-stream-head">
            <span className="sk-speed-arrow down">↓</span>
            <span>{t("overview.download")}</span>
          </div>
          <div className="sk-live-stream-value">{formatSpeed(down)}</div>
          {totalDown != null && <div className="sk-live-stream-total">{formatBytes(totalDown)} total</div>}
          <ActivityBars level={down} tone="down" />
          <Sparkline data={downSeries} height={42} color="var(--sk-accent)" />
        </div>

        <div className="sk-live-side">
          <div className="sk-live-side-block">
            <span className="sk-live-side-label">{t("overview.xrayCore")}</span>
            <p className="sk-live-side-hint">
              {running ? t("overview.coreRunningHint") : (core.data?.startup_error || t("overview.coreStoppedHint"))}
            </p>
            <div className="sk-core-actions">
              {running ? (
                <Button variant="danger" size="sm" disabled={busy} onClick={() => act("stop")}>
                  {t("overview.stop")}
                </Button>
              ) : (
                <Button variant="primary" size="sm" disabled={busy} onClick={() => act("start")}>
                  {t("overview.start")}
                </Button>
              )}
              <Button variant="ghost" size="sm" disabled={busy} onClick={() => act("restart")}>
                <IcRefresh className="sk-ico" /> {t("overview.restart")}
              </Button>
            </div>
          </div>
          <div className="sk-live-uptime">
            <div className="sk-live-uptime-cell">
              <IcBolt />
              <div>
                <span>Xray</span>
                <strong>{formatUptime(xray)}</strong>
              </div>
            </div>
            <div className="sk-live-uptime-cell">
              <IcMonitor />
              <div>
                <span>{t("overview.uptimeOs")}</span>
                <strong>{formatUptime(os)}</strong>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export const Overview: FC = () => {
  const { t, i18n } = useTranslation();
  const { admin, isEnabled, hasPermission } = useApp();
  const { setOpen } = useCopilot();
  const [backupOpen, setBackupOpen] = useState(false);
  const canBackup = hasPermission("backup:read");
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
  type ResellerOnlineRow = {
    username: string;
    is_sudo?: boolean;
    users_count?: number | null;
    online_users?: number | null;
  };
  const resellerOnline = useFetch<ResellerOnlineRow[]>(
    () => (admin?.is_sudo ? api.get("/admins") : Promise.resolve([])),
    [admin?.is_sudo],
  );
  usePolling(() => {
    if (admin?.is_sudo) resellerOnline.reload({ background: true });
  }, 15000);
  const payProviders = useFetch<string[]>(
    () => (isEnabled("billing") ? api.get("/billing/payment-providers") : Promise.resolve([])),
    [isEnabled("billing")],
  );
  const allProviders = useFetch<string[]>(
    () => (isEnabled("billing") ? api.get("/billing/providers") : Promise.resolve([])),
    [isEnabled("billing")],
  );
  const payMethods = useMemo(() => {
    const list = [...(payProviders.data || [])];
    if ((allProviders.data || []).includes("card") && !list.includes("card")) list.push("card");
    return list;
  }, [payProviders.data, allProviders.data]);
  const payActive = payMethods.length > 0;
  const gatewayIncome = useFetch<GatewayIncome>(
    () => (
      isEnabled("billing") && payActive
        ? api.get("/billing/gateway-income?payments_limit=1")
        : Promise.resolve(null as unknown as GatewayIncome)
    ),
    [isEnabled("billing"), payActive],
  );
  const ws = workspace.data;
  const [rt, setRt] = useState<RealtimeStats | null>(null);
  const [rtStale, setRtStale] = useState(false);
  const [sysFetchedAt, setSysFetchedAt] = useState(() => Date.now());
  const [, setTick] = useState(0);

  usePolling(() => {
    api.get<RealtimeStats>("/analytics/realtime")
      .then((d) => { setRt(d); setRtStale(false); })
      .catch(() => setRtStale(true));
  }, 3000);

  usePolling(() => {
    sys.reload({ background: true });
  }, 8000);

  useEffect(() => {
    if (sys.data) setSysFetchedAt(Date.now());
  }, [sys.data]);

  useEffect(() => {
    const id = window.setInterval(() => setTick((n) => n + 1), 1000);
    return () => window.clearInterval(id);
  }, []);

  useLiveReload(() => {
    top.reload({ background: true });
    protoUsage.reload({ background: true });
    nodes.reload({ background: true });
    inbounds.reload({ background: true });
    nodesUsage.reload({ background: true });
    workspace.reload({ background: true });
    mrr.reload({ background: true });
    payProviders.reload({ background: true });
    allProviders.reload({ background: true });
    if (payActive) gatewayIncome.reload({ background: true });
  }, 20000);

  const { hasUpdate, check, openUpdateModal } = usePanelUpdate();
  const s = sys.data;
  const elapsedSec = Math.max(0, Math.floor((Date.now() - sysFetchedAt) / 1000));
  const liveXrayUptime = s?.xray_uptime != null ? s.xray_uptime + elapsedSec : undefined;
  const liveOsUptime = s?.os_uptime != null ? s.os_uptime + elapsedSec : undefined;

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

  // User-facing polarity (not server NIC TX/RX):
  // Upload  = client → server  ≈ API incoming / Xray uplink
  // Download = server → client ≈ API outgoing / Xray downlink
  // Matches Node traffic ↑ uplink / ↓ downlink and typical VPN usage
  // (download >> upload), unlike 3x-ui's server-centric Overall Speed labels.
  const up = rt?.incoming_bandwidth_speed ?? s?.incoming_bandwidth_speed ?? 0;
  const down = rt?.outgoing_bandwidth_speed ?? s?.outgoing_bandwidth_speed ?? 0;

  return (
    <div className="sk-overview sk-home-min sk-home-alive">
      <div className="sk-home-ambient" aria-hidden />

      <PageHeader
        title={t("overview.title")}
        subtitle={t("overview.subtitle")}
        actions={(
          <div className="sk-row" style={{ gap: 8, flexWrap: "wrap" }}>
            {canBackup && (
              <Button variant="primary" onClick={() => setBackupOpen(true)}>
                <IcDownload className="sk-ico" /> {t("overview.backupRestore")}
              </Button>
            )}
            {admin?.is_sudo && (
              <Button variant="ghost" onClick={() => setOpen(true)}>{t("overview.openGuide")}</Button>
            )}
          </div>
        )}
      />

      {canBackup && (
        <BackupRestoreModal open={backupOpen} onClose={() => setBackupOpen(false)} />
      )}

      {hasUpdate && check && (
        <Callout tone="info" className="compact sk-mb-16">
          {t("system.updatesBehind", {
            from: check.current_version,
            to: check.remote_version,
          })}{" "}
          <button type="button" className="sk-link-btn" style={{ marginInlineStart: 8, fontWeight: 600 }} onClick={openUpdateModal}>
            {t("system.applyUpdates")} →
          </button>
        </Callout>
      )}

      {!admin?.is_sudo && ws?.wallet_blocked && (
        <Callout tone="danger" title={t("overview.walletBlockedTitle")} className="sk-mb-16">
          {t("overview.walletBlockedHint", {
            cost: (ws.pending_usage_cost ?? 0).toLocaleString(),
            balance: (ws.wallet_balance ?? 0).toLocaleString(),
            currency: ws.currency_label || "",
            traffic: formatBytes(ws.pending_usage_bytes ?? 0),
          })}
        </Callout>
      )}
      {!admin?.is_sudo && (ws?.prepaid_traffic_remaining ?? 0) <= 0 && (
        <Callout tone="warn" title={t("overview.packageExhaustedTitle")} className="sk-mb-16">
          <div className="sk-stack" style={{ gap: 10 }}>
            <span>{t("overview.packageExhaustedHint")}</span>
            <div>
              <Link to="/billing?billingTab=packages">
                <Button variant="primary" size="sm">{t("overview.buyPackageCta")}</Button>
              </Link>
            </div>
          </div>
        </Callout>
      )}
      {!admin?.is_sudo && !ws?.wallet_blocked && ws?.wallet_low && (
        <Callout tone="warn" title={t("overview.lowWalletTitle")} className="sk-mb-16">
          {t("overview.lowWalletHint")}
        </Callout>
      )}
      {!admin?.is_sudo && (ws?.capped_users ?? 0) > 0 && (
        <Callout tone="warn" title={t("overview.cappedUsersTitle")} className="sk-mb-16">
          {t("overview.cappedUsersHint", { count: ws?.capped_users ?? 0 })}
        </Callout>
      )}

      {admin?.is_sudo && healthItems.length > 0 && !setupDone && (
        <div className="sk-mb-20"><HealthChecklist items={healthItems} /></div>
      )}

      {admin?.is_sudo && !setupDone && (
        <div className="sk-quick-actions sk-mb-20">
          <Link to="/servers?tab=nodes" className="sk-quick-card accent">
            <IcServer className="sk-ico" /><span>{t("overview.quickAddServer")}</span>
          </Link>
          <Link to="/connection?tab=inbounds" className="sk-quick-card">
            <IcBolt className="sk-ico" /><span>{t("overview.quickAddInbound")}</span>
          </Link>
          <Link to="/users" className="sk-quick-card ok">
            <IcUsers className="sk-ico" /><span>{t("overview.quickAddUser")}</span>
          </Link>
        </div>
      )}

      {admin?.is_sudo && (
        <Section>
          <LiveHero
            up={up}
            down={down}
            totalUp={s?.incoming_bandwidth}
            totalDown={s?.outgoing_bandwidth}
            stale={rtStale}
            xray={liveXrayUptime}
            os={liveOsUptime}
          />
        </Section>
      )}

      <Section title={t("overview.fleet", "Fleet")}>
        {sys.loading && !s ? (
          <Card><SkeletonRows rows={2} cols={4} /></Card>
        ) : (
          <div className="sk-fleet-stack">
            <div className={`sk-kpi-grid${admin?.is_sudo ? "" : " is-reseller"}`}>
              <KpiTile label={t("overview.totalUsers")} value={s?.total_user} to="/users" />
              <KpiTile
                live
                label={t("overview.onlineUsers")}
                value={rt?.online_users ?? s?.online_users}
                sub={t("users.stats.online")}
              />
              <KpiTile
                label={t("overview.activeUsers")}
                value={rt?.users_active ?? s?.users_active}
                sub={s && (rt?.users_active ?? s.users_active) != null && s.total_user > 0
                  ? `${Math.round(((rt?.users_active ?? s.users_active) / s.total_user) * 100)}%`
                  : undefined}
              />
              <KpiTile
                label={t("overview.inactiveUsers")}
                value={s ? Math.max(0, s.total_user - s.users_active) : null}
                sub={`${s?.users_disabled ?? 0} ${t("users.status.disabled")}`}
              />
              {admin?.is_sudo ? (
                <KpiTile label={t("overview.nodes")} value={rt?.nodes_connected ?? connectedNodes} to="/servers?tab=nodes" />
              ) : (
                <KpiTile label={t("overview.myNodes")} value={ws?.nodes_count} />
              )}
            </div>
            {!admin?.is_sudo && ws?.wallet_balance != null ? (
              <ResellerCommerceStrip ws={ws} />
            ) : null}
          </div>
        )}
      </Section>

      {admin?.is_sudo && (
        <Section
          title={t("overview.resellerOnlineTitle")}
          action={(
            <Link to="/users" className="sk-pay-pulse-link">{t("overview.resellerOnlineOpen")}</Link>
          )}
        >
          {resellerOnline.loading && !resellerOnline.data ? (
            <Card><SkeletonRows rows={3} cols={3} /></Card>
          ) : (
            (() => {
              const rows = (resellerOnline.data || [])
                .filter((a) => !a.is_sudo)
                .sort((a, b) => (b.online_users ?? 0) - (a.online_users ?? 0));
              if (!rows.length) {
                return <div className="sk-muted sk-center" style={{ padding: 16 }}>{t("common.noData")}</div>;
              }
              return (
                <div className="sk-table-wrap">
                  <table className="sk-table">
                    <thead>
                      <tr>
                        <th>{t("common.username")}</th>
                        <th className="sk-num">{t("overview.totalUsers")}</th>
                        <th className="sk-num">{t("overview.onlineUsers")}</th>
                        <th className="sk-actions">{t("common.actions")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r) => (
                        <tr key={r.username}>
                          <td style={{ fontWeight: 600 }}>{r.username}</td>
                          <td className="sk-num">{(r.users_count ?? 0).toLocaleString()}</td>
                          <td className="sk-num" style={{ fontWeight: 700, color: (r.online_users ?? 0) > 0 ? "var(--sk-ok)" : undefined }}>
                            {(r.online_users ?? 0).toLocaleString()}
                          </td>
                          <td className="sk-actions">
                            <Link to={`/users?admin=${encodeURIComponent(r.username)}`} className="sk-btn sm ghost">
                              {t("overview.viewResellerUsers")}
                            </Link>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              );
            })()
          )}
        </Section>
      )}

      {admin?.is_sudo && s && (
        <Section title={t("overview.systemResources", "System")}>
          <SystemVitals
            cpu={s.cpu_usage}
            cpuCores={s.cpu_cores}
            memUsed={s.mem_used}
            memTotal={s.mem_total}
            diskUsed={s.disk_used}
            diskTotal={s.disk_total}
          />
        </Section>
      )}

      <Section title={t("overview.usage", "Usage")}>
        <div className="sk-usage-grid">
          <article className="sk-usage-board">
            <header className="sk-usage-board-head">
              <div>
                <h3>{t("analytics.protocolUsage", "Usage by protocol")}</h3>
                <p>{t("overview.usageProtocolHint", "Share of total recorded traffic")}</p>
              </div>
            </header>
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
              <div className="sk-muted sk-center" style={{ padding: 20 }}>{t("common.noData")}</div>
            )}
          </article>

          {admin?.is_sudo && nodesUsage.data?.usages?.length ? (
            <article className="sk-usage-board">
              <header className="sk-usage-board-head">
                <div>
                  <h3>{t("overview.nodesUsage")}</h3>
                  <p>{t("overview.usageNodesHint", "Last 30 days across connected nodes")}</p>
                </div>
              </header>
              <RankBars
                data={nodesUsage.data.usages.map((n) => ({
                  label: n.node_name,
                  value: n.uplink + n.downlink,
                  sub: `↑ ${formatBytes(n.uplink, 0)}  ↓ ${formatBytes(n.downlink, 0)}`,
                }))}
                format={(v) => formatBytes(v, 0)}
              />
            </article>
          ) : null}

          <article className="sk-usage-board">
            <header className="sk-usage-board-head">
              <div>
                <h3>{t("overview.topUsers")}</h3>
                <p>{t("overview.usageUsersHint", "Highest consumers on this panel")}</p>
              </div>
              <Link to="/users" className="sk-usage-link">
                {t("common.viewAll", "View all")}
                <span aria-hidden>→</span>
              </Link>
            </header>
            {top.loading ? (
              <SkeletonRows rows={3} cols={2} />
            ) : top.error ? (
              <EmptyState title={t("common.error")} desc={top.error} action={<Button onClick={top.reload}>{t("common.retry")}</Button>} />
            ) : top.data?.length ? (
              <RankBars
                compact
                data={top.data.map((u) => ({ label: u.username, value: u.used_traffic }))}
                format={(n) => formatBytes(n, 0)}
              />
            ) : (
              <div className="sk-muted sk-center" style={{ padding: 20 }}>{t("common.noData")}</div>
            )}
          </article>
        </div>
      </Section>

      {isEnabled("billing") && payActive && (
        <Section>
          {gatewayIncome.loading && !gatewayIncome.data ? (
            <div className="sk-pay-pulse"><SkeletonRows rows={3} cols={4} /></div>
          ) : gatewayIncome.data ? (
            <PaymentPulse
              income={gatewayIncome.data}
              methods={payMethods}
              isSudo={!!admin?.is_sudo}
            />
          ) : null}
        </Section>
      )}

      {admin?.is_sudo && mrr.data && (
        <Section title={t("overview.mrrTitle")}>
          <div className="sk-home-mrr">
            <div className="sk-home-mrr-cell">
              <span className="sk-home-mrr-label">{t("overview.mrrRevenue")}</span>
              <LiveValue className="sk-home-mrr-value" value={mrr.data.total_revenue} format={(n) => Math.round(n).toLocaleString()} />
            </div>
            <div className="sk-home-mrr-cell">
              <span className="sk-home-mrr-label">{t("overview.mrrFloat")}</span>
              <LiveValue className="sk-home-mrr-value" value={mrr.data.wallet_float} format={(n) => Math.round(n).toLocaleString()} />
            </div>
            <div className="sk-home-mrr-cell">
              <span className="sk-home-mrr-label">{t("overview.mrrResellers")}</span>
              <LiveValue className="sk-home-mrr-value" value={mrr.data.active_resellers} />
            </div>
          </div>
        </Section>
      )}

      <div className="sk-home-foot">
        {t("overview.version")} {s?.version} · {new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "medium" }).format(new Date())}
      </div>
    </div>
  );
};
