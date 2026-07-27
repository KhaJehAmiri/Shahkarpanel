import { FC, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useApp } from "../context/AppContext";
import { RailHubLayout } from "../components/RailHubLayout";
import { type RailGroup } from "../components/SectionRail";
import { Nodes } from "./Nodes";
import { WireGuard } from "./WireGuard";
import { SingBox } from "./SingBox";
import { ServicesManager } from "./ServicesManager";
import { TunnelsPage } from "./TunnelsPage";
import { DedicatedIP } from "./DedicatedIP";

export const ServersHub: FC = () => {
  const { t } = useTranslation();
  const { admin, isEnabled } = useApp();
  const sudo = !!admin?.is_sudo;
  const clientApi = isEnabled("client_api");
  const tunneling = isEnabled("tunneling");

  const groups: RailGroup[] = useMemo(() => {
    const fleet: RailGroup = {
      id: "fleet",
      label: t("hub.groupFleet"),
      items: [
        { id: "nodes", label: t("hub.tabNodes") },
        ...(sudo ? [{ id: "services", label: t("hub.tabServices") }] : []),
      ],
    };
    if (!sudo) return [fleet];

    const vpn: RailGroup = {
      id: "vpn",
      label: t("hub.groupVpn"),
      items: [
        { id: "wireguard", label: t("hub.tabWireGuard") },
        { id: "h2", label: t("hub.tabH2") },
      ],
    };
    const networkItems = [
      ...(tunneling ? [{ id: "tunnels", label: t("hub.tabTunnels") }] : []),
      ...(clientApi ? [{ id: "dedip", label: t("hub.tabDedip") }] : []),
    ];
    const out = [fleet, vpn];
    if (networkItems.length) {
      out.push({ id: "network", label: t("hub.groupNetwork"), items: networkItems });
    }
    return out;
  }, [t, sudo, tunneling, clientApi]);

  return (
    <RailHubLayout
      title={t("hub.serversTitle")}
      subtitle={t("hub.serversSubtitle")}
      description={t("hub.serversDesc")}
      defaultTab="nodes"
      groups={groups}
    >
      {(tab) => {
        if (tab === "services") return <ServicesManager embedded />;
        if (tab === "wireguard") return <WireGuard embedded />;
        if (tab === "h2") return <SingBox embedded />;
        if (tab === "tunnels") return <TunnelsPage embedded />;
        if (tab === "dedip") return <DedicatedIP embedded />;
        return <Nodes />;
      }}
    </RailHubLayout>
  );
};
