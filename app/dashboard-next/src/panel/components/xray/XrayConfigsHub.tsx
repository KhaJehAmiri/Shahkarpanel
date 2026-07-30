import { FC, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useXrayConfig } from "./useXrayConfig";
import { BasicsSection } from "./BasicsSection";
import { OutboundsSection } from "./OutboundsSection";
import { RoutingSection } from "./RoutingSection";
import { DnsSection } from "./DnsSection";
import { JsonSection } from "./JsonSection";
import { CoreLogSection } from "./CoreLogSection";
import { Button, Card, EmptyState, SkeletonRows, Tabs, useToast } from "../ui";
import { IcRefresh } from "../icons";

export const XrayConfigsHub: FC<{
  /** When set, only these tabs are shown (ids: outbounds | routing | dns | basics | json). */
  visibleTabs?: string[];
  initialTab?: string;
}> = ({ visibleTabs, initialTab }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const { config, setConfig, loading, error, saving, reload, save } = useXrayConfig();
  const allTabs = useMemo(() => [
    { id: "outbounds", label: t("xray.tabOutbounds") },
    { id: "routing", label: t("xray.tabRouting") },
    { id: "dns", label: t("xray.tabDns") },
    { id: "basics", label: t("xray.tabBasics") },
    { id: "json", label: t("xray.tabJson") },
    { id: "logs", label: t("xray.tabLogs") },
  ], [t]);
  const tabs = useMemo(
    () => (visibleTabs?.length ? allTabs.filter((x) => visibleTabs.includes(x.id)) : allTabs),
    [allTabs, visibleTabs],
  );
  const [tab, setTab] = useState(() =>
    initialTab && tabs.some((x) => x.id === initialTab) ? initialTab : tabs[0]?.id ?? "outbounds",
  );

  useEffect(() => {
    reload();
  }, [reload]);

  useEffect(() => {
    if (initialTab && tabs.some((x) => x.id === initialTab)) setTab(initialTab);
  }, [initialTab, tabs]);

  const persist = async (next?: Record<string, unknown>) => {
    const payload = next ?? config;
    if (!payload) return;
    try {
      await save(payload);
      toast.push(t("xray.savedRestart"), "success");
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.saveFailed"), "error");
    }
  };

  if (loading) return <Card><SkeletonRows rows={6} cols={4} /></Card>;
  if (error) {
    return (
      <EmptyState
        title={t("common.error")}
        desc={error}
        action={<Button onClick={reload}><IcRefresh className="sk-ico" /> {t("common.retry")}</Button>}
      />
    );
  }
  if (!config) return null;

  const onChange = (c: Record<string, unknown>) => setConfig(c);

  return (
    <div>
      <div className="sk-row" style={{ justifyContent: "flex-end", marginBottom: 12 }}>
        <Button variant="ghost" onClick={reload} disabled={saving}>
          <IcRefresh className="sk-ico" /> {t("common.refresh")}
        </Button>
      </div>
      {tabs.length > 1 && <Tabs active={tab} onChange={setTab} tabs={tabs} />}
      {tab === "outbounds" && (
        <OutboundsSection config={config} onChange={onChange} saving={saving} />
      )}
      {tab === "routing" && (
        <RoutingSection config={config} onChange={onChange} onSave={() => persist()} saving={saving} />
      )}
      {tab === "dns" && (
        <DnsSection config={config} onChange={onChange} onSave={() => persist()} saving={saving} />
      )}
      {tab === "basics" && (
        <BasicsSection config={config} onChange={onChange} onSave={() => persist()} saving={saving} />
      )}
      {tab === "json" && (
        <JsonSection config={config} onSave={(parsed) => persist(parsed)} saving={saving} />
      )}
      {tab === "logs" && <CoreLogSection />}
    </div>
  );
};
