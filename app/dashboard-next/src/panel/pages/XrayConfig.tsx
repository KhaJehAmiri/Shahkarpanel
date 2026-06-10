import { FC } from "react";
import { SudoGate, SudoOnly } from "../components/SudoGate";
import { XrayConfigsHub } from "../components/xray/XrayConfigsHub";

export const XrayConfig: FC<{ embedded?: boolean }> = ({ embedded }) => (
  embedded ? <SudoOnly><XrayConfigsHub /></SudoOnly> : (
    <SudoGate titleKey="xrayPage.title" subtitleKey="xrayPage.subtitle" descKey="xrayPage.description">
      <XrayConfigsHub />
    </SudoGate>
  )
);
