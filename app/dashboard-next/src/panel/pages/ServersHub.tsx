import { FC } from "react";
import { useTranslation } from "react-i18next";
import { useApp } from "../context/AppContext";
import { HubLayout } from "../components/HubLayout";
import { Nodes } from "./Nodes";
import { WireGuard } from "./WireGuard";
import { SingBox } from "./SingBox";
import { TunnelsPage } from "./TunnelsPage";
import { DedicatedIP } from "./DedicatedIP";

export const ServersHub: FC = () => {
  const { t } = useTranslation();
  const { admin, isEnabled } = useApp();
  const sudo = !!admin?.is_sudo;
  const clientApi = isEnabled("client_api");
  const tunneling = isEnabled("tunneling");

  return (
    <HubLayout
      title={t("hub.serversTitle")}
      subtitle={t("hub.serversSubtitle")}
      description={t("hub.serversDesc")}
      defaultTab="nodes"
      tabs={[
        { id: "nodes", label: t("hub.tabNodes") },
        { id: "wireguard", label: t("hub.tabWireGuard"), hidden: !sudo },
        { id: "h2", label: t("hub.tabH2"), hidden: !sudo },
        // Tunnels API is sudo-only; showing the tab to resellers only produces 403s.
        { id: "tunnels", label: t("hub.tabTunnels"), hidden: !tunneling || !sudo },
        { id: "dedip", label: t("hub.tabDedip"), hidden: !clientApi || !sudo },
      ]}
    >
      {(tab) => {
        if (tab === "wireguard") return <WireGuard embedded />;
        if (tab === "h2") return <SingBox embedded />;
        if (tab === "tunnels") return <TunnelsPage embedded />;
        if (tab === "dedip") return <DedicatedIP embedded />;
        return <Nodes />;
      }}
    </HubLayout>
  );
};
