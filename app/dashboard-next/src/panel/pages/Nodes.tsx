import { FC } from "react";
import { useTranslation } from "react-i18next";
import { useApp } from "../context/AppContext";
import { SudoGate } from "../components/SudoGate";
import { Callout } from "../components/ui";
import { NodesTab } from "./Infrastructure";

export const Nodes: FC = () => {
  const { t } = useTranslation();
  const { admin } = useApp();

  if (admin?.role === "support") {
    return (
      <SudoGate titleKey="nodes.title" subtitleKey="nodes.subtitle" descKey="nodes.description">
        <NodesTab />
      </SudoGate>
    );
  }

  return (
    <div>
      {!admin?.is_sudo && (
        <Callout tone="info" title={t("resellers.myNodesTitle")}>
          {t("resellers.myNodesHint")}
        </Callout>
      )}
      <NodesTab resellerMode={!admin?.is_sudo} />
    </div>
  );
};
