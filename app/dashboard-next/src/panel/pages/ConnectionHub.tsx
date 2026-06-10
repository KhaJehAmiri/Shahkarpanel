import { FC } from "react";
import { useTranslation } from "react-i18next";
import { useApp } from "../context/AppContext";
import { HubLayout } from "../components/HubLayout";
import { SudoOnly } from "../components/SudoGate";
import { XrayConfigsHub } from "../components/xray/XrayConfigsHub";
import { Inbounds } from "./Inbounds";
import { Hosts } from "./Hosts";
import { Callout } from "../components/ui";

export const ConnectionHub: FC = () => {
  const { t } = useTranslation();
  const { admin, expertMode } = useApp();
  const isSudo = !!admin?.is_sudo;

  return (
    <HubLayout
      title={t("hub.connectionTitle")}
      subtitle={t("hub.connectionSubtitle")}
      description={t("hub.connectionDesc")}
      defaultTab="inbounds"
      tabs={[
        { id: "inbounds", label: t("hub.tabInbounds") },
        { id: "outbounds", label: t("hub.tabOutbounds"), hidden: !isSudo },
        { id: "routing", label: t("hub.tabRouting"), hidden: !isSudo },
        { id: "hosts", label: t("hub.tabHosts") },
        { id: "advanced", label: t("hub.tabAdvanced"), hidden: !expertMode || !isSudo },
      ]}
    >
      {(tab) => {
        if (tab === "outbounds") {
          return (
            <SudoOnly>
              <XrayConfigsHub visibleTabs={["outbounds"]} initialTab="outbounds" />
            </SudoOnly>
          );
        }
        if (tab === "routing") {
          return (
            <SudoOnly>
              <XrayConfigsHub visibleTabs={["routing"]} initialTab="routing" />
            </SudoOnly>
          );
        }
        if (tab === "hosts") return <Hosts embedded />;
        if (tab === "advanced") {
          return (
            <SudoOnly>
              <XrayConfigsHub visibleTabs={["dns", "basics", "json"]} initialTab="dns" />
            </SudoOnly>
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
