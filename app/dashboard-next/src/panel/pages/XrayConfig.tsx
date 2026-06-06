import { FC } from "react";
import { SudoGate } from "../components/SudoGate";
import { XrayConfigsHub } from "../components/xray/XrayConfigsHub";

export const XrayConfig: FC = () => (
  <SudoGate titleKey="xrayPage.title" subtitleKey="xrayPage.subtitle" descKey="xrayPage.description">
    <XrayConfigsHub />
  </SudoGate>
);
