import { FC } from "react";
import { useTranslation } from "react-i18next";
import { useApp } from "../context/AppContext";
import { HubLayout } from "../components/HubLayout";
import { CoreReadGate } from "../components/SudoGate";
import { XrayConfigsHub } from "../components/xray/XrayConfigsHub";
import { Inbounds } from "./Inbounds";
import { Hosts } from "./Hosts";
import { SubscriptionEndpoints } from "./SubscriptionEndpoints";
import { Callout } from "../components/ui";

export const ConnectionHub: FC = () => {
  const { t } = useTranslation();
  const { expertMode, hasPermission } = useApp();
  const canReadCore = hasPermission("core:read");

  return (
    <HubLayout
      title={t("hub.connectionTitle")}
      subtitle={t("hub.connectionSubtitle")}
      description={t("hub.connectionDesc")}
      defaultTab="inbounds"
      tabs={[
        { id: "inbounds", label: t("hub.tabInbounds") },
        { id: "subscription", label: t("hub.tabSubscription") },
        { id: "outbounds", label: t("hub.tabOutbounds"), hidden: !canReadCore },
        { id: "routing", label: t("hub.tabRouting"), hidden: !canReadCore },
        { id: "hosts", label: t("hub.tabHosts") },
        { id: "advanced", label: t("hub.tabAdvanced"), hidden: !expertMode || !canReadCore },
      ]}
    >
      {(tab) => {
        if (tab === "subscription") return <SubscriptionEndpoints />;
        if (tab === "outbounds") {
          return (
            <CoreReadGate>
              <XrayConfigsHub visibleTabs={["outbounds"]} initialTab="outbounds" />
            </CoreReadGate>
          );
        }
        if (tab === "routing") {
          return (
            <CoreReadGate>
              <XrayConfigsHub visibleTabs={["routing"]} initialTab="routing" />
            </CoreReadGate>
          );
        }
        if (tab === "hosts") return <Hosts embedded />;
        if (tab === "advanced") {
          return (
            <CoreReadGate>
              <XrayConfigsHub visibleTabs={["dns", "basics", "json"]} initialTab="dns" />
            </CoreReadGate>
          );
        }
        return (
          <>
            <Callout tone="info" title={t("hub.inboundHintTitle")}>{t("hub.inboundHintBody")}</Callout>
            <div style={{ marginTop: 14 }}><Inbounds embedded /></div>
          </>
        );
      }}
    </HubLayout>
  );
};
