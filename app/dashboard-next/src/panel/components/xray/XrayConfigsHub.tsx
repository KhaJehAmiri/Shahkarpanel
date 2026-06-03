import { FC, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useXrayConfig } from "./useXrayConfig";
import { BasicsSection } from "./BasicsSection";
import { InboundsSection } from "./InboundsSection";
import { OutboundsSection } from "./OutboundsSection";
import { RoutingSection } from "./RoutingSection";
import { DnsSection } from "./DnsSection";
import { JsonSection } from "./JsonSection";
import { Button, Card, EmptyState, SkeletonRows, Tabs, useToast } from "../ui";
import { IcRefresh } from "../icons";

export const XrayConfigsHub: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const { config, setConfig, loading, error, saving, reload, save } = useXrayConfig();
  const [tab, setTab] = useState("inbounds");

  useEffect(() => {
    reload();
  }, [reload]);

  const tabs = [
    { id: "inbounds", label: t("xray.tabInbounds") },
    { id: "outbounds", label: t("xray.tabOutbounds") },
    { id: "routing", label: t("xray.tabRouting") },
    { id: "dns", label: t("xray.tabDns") },
    { id: "basics", label: t("xray.tabBasics") },
    { id: "json", label: t("xray.tabJson") },
  ];

  const persist = async (next?: Record<string, unknown>) => {
    const payload = next ?? config;
    if (!payload) return;
    try {
      await save(payload);
      toast.push(t("xray.savedRestart"), "success");
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : "Save failed", "error");
    }
  };

  if (loading) return <Card><SkeletonRows rows={6} cols={4} /></Card>;
  if (error) {
    return (
      <EmptyState
        title={t("common.error")}
        desc={error}
        action={<Button onClick={reload}><IcRefresh className="nx-ico" /> {t("common.retry")}</Button>}
      />
    );
  }
  if (!config) return null;

  const onChange = (c: Record<string, unknown>) => setConfig(c);

  return (
    <div>
      <div className="nx-row" style={{ justifyContent: "flex-end", marginBottom: 12 }}>
        <Button variant="ghost" onClick={reload} disabled={saving}>
          <IcRefresh className="nx-ico" /> {t("common.refresh")}
        </Button>
      </div>
      <Tabs active={tab} onChange={setTab} tabs={tabs} />
      {tab === "inbounds" && (
        <InboundsSection config={config} onChange={onChange} onSave={() => persist()} saving={saving} />
      )}
      {tab === "outbounds" && (
        <OutboundsSection config={config} onChange={onChange} onSave={() => persist()} saving={saving} />
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
    </div>
  );
};
