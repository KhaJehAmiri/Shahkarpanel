import { FC } from "react";
import { SudoGate, SudoOnly } from "../components/SudoGate";
import { HostsTab } from "./Infrastructure";

export const Hosts: FC<{ embedded?: boolean }> = ({ embedded }) => (
  embedded ? <SudoOnly><HostsTab /></SudoOnly> : (
    <SudoGate titleKey="hosts.title" subtitleKey="hosts.subtitle" descKey="hosts.description">
      <HostsTab />
    </SudoGate>
  )
);
