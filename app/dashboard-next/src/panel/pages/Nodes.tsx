import { FC } from "react";
import { useTranslation } from "react-i18next";
import { useApp } from "../context/AppContext";
import { SudoGate } from "../components/SudoGate";
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
    <div className="nx-stack nx-hub-panel">
      {!admin?.is_sudo && (
        <p className="nx-hub-lede">
          <strong>{t("resellers.myNodesTitle")}. </strong>
          {t("resellers.myNodesHint")}
        </p>
      )}
      <NodesTab resellerMode={!admin?.is_sudo} />
    </div>
  );
};
