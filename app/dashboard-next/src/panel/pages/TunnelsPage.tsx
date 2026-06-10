import { FC } from "react";
import { SudoGate, SudoOnly } from "../components/SudoGate";
import { TunnelsTab } from "./Infrastructure";

export const TunnelsPage: FC<{ embedded?: boolean }> = ({ embedded }) => (
  embedded ? <SudoOnly><TunnelsTab /></SudoOnly> : (
    <SudoGate titleKey="tunnels.title" subtitleKey="tunnels.subtitle" descKey="tunnels.description">
      <TunnelsTab />
    </SudoGate>
  )
);
