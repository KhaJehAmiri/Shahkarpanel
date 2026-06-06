import { FC } from "react";
import { SudoGate } from "../components/SudoGate";
import { NodesTab } from "./Infrastructure";

export const Nodes: FC = () => (
  <SudoGate titleKey="nodes.title" subtitleKey="nodes.subtitle" descKey="nodes.description">
    <NodesTab />
  </SudoGate>
);
