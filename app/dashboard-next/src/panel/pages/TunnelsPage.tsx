import { FC } from "react";
import { SudoGate } from "../components/SudoGate";
import { TunnelsTab } from "./Infrastructure";

export const TunnelsPage: FC = () => (
  <SudoGate titleKey="tunnels.title" subtitleKey="tunnels.subtitle" descKey="tunnels.description">
    <TunnelsTab />
  </SudoGate>
);
