import { FC } from "react";
import { HostsGate } from "../components/SudoGate";
import { HostsTab } from "./Infrastructure";

export const Hosts: FC<{ embedded?: boolean }> = ({ embedded }) => (
  embedded ? (
    <HostsGate><HostsTab /></HostsGate>
  ) : (
    <HostsGate titleKey="hosts.title" subtitleKey="hosts.subtitle" descKey="hosts.description">
      <HostsTab />
    </HostsGate>
  )
);
