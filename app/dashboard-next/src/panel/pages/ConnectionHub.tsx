import { FC, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useApp } from "../context/AppContext";
import { RailHubLayout } from "../components/RailHubLayout";
import { type RailGroup } from "../components/SectionRail";
import { CoreReadGate } from "../components/SudoGate";
import { XrayConfigsHub } from "../components/xray/XrayConfigsHub";
import { Inbounds } from "./Inbounds";
import { Hosts } from "./Hosts";
import { SubscriptionEndpoints } from "./SubscriptionEndpoints";

export const ConnectionHub: FC = () => {
  const { t } = useTranslation();
  const { expertMode, hasPermission } = useApp();
  const canReadCore = hasPermission("core:read");

  const groups: RailGroup[] = useMemo(() => {
    const listeners: RailGroup = {
      id: "listeners",
      label: t("hub.groupListeners"),
      items: [
        { id: "inbounds", label: t("hub.tabInbounds") },
        { id: "subscription", label: t("hub.tabSubscription") },
        { id: "hosts", label: t("hub.tabHosts") },
      ],
    };
    const out = [listeners];
    if (canReadCore) {
      out.push({
        id: "core",
        label: t("hub.groupCore"),
        items: [
          { id: "outbounds", label: t("hub.tabOutbounds") },
          { id: "routing", label: t("hub.tabRouting") },
        ],
      });
    }
    if (expertMode && canReadCore) {
      out.push({
        id: "expert",
        label: t("hub.groupExpert"),
        items: [{ id: "advanced", label: t("hub.tabAdvanced") }],
      });
    }
    return out;
  }, [t, canReadCore, expertMode]);

  return (
    <RailHubLayout
      title={t("hub.connectionTitle")}
      subtitle={t("hub.connectionSubtitle")}
      description={t("hub.connectionDesc")}
      defaultTab="inbounds"
      groups={groups}
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
          <div className="sk-stack sk-hub-panel">
            <p className="sk-hub-lede">
              <strong>{t("hub.inboundHintTitle")}. </strong>
              {t("hub.inboundHintBody")}
            </p>
            <Inbounds embedded />
          </div>
        );
      }}
    </RailHubLayout>
  );
};
