import { FC } from "react";
import { SudoGate } from "../components/SudoGate";
import { HostsTab } from "./Infrastructure";

export const Hosts: FC = () => (
  <SudoGate titleKey="hosts.title" subtitleKey="hosts.subtitle" descKey="hosts.description">
    <HostsTab />
  </SudoGate>
);
