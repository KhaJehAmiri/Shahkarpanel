import { FC } from "react";
import { useTranslation } from "react-i18next";
import { useApp } from "../context/AppContext";
import { HubLayout } from "../components/HubLayout";
import { Billing } from "./Billing";
import { Resellers } from "./Resellers";
import { Analytics } from "./Analytics";
import { Automation } from "./Automation";
import { CommercialSettings } from "../components/CommercialSettings";

export const BusinessHub: FC = () => {
  const { t } = useTranslation();
  const { admin, isEnabled } = useApp();
  // Support role lacks billing:read — backend would 403 every billing call.
  const isSupport = !admin?.is_sudo && admin?.role === "support";
  const billing = isEnabled("billing") && !isSupport;

  return (
    <HubLayout
      title={t("hub.businessTitle")}
      subtitle={t("hub.businessSubtitle")}
      description={t("hub.businessDesc")}
      defaultTab={billing ? "billing" : "resellers"}
      tabs={[
        { id: "billing", label: t("hub.tabBilling"), hidden: !billing },
        { id: "resellers", label: t("hub.tabResellers") },
        { id: "analytics", label: t("hub.tabAnalytics") },
        { id: "automation", label: t("hub.tabAutomation"), hidden: !admin?.is_sudo },
        { id: "commercial", label: t("hub.tabCommercial"), hidden: !admin?.is_sudo || !billing },
      ]}
    >
      {(tab) => {
        if (tab === "resellers") return <Resellers embedded />;
        if (tab === "analytics") return <Analytics embedded />;
        if (tab === "automation") return <Automation embedded />;
        if (tab === "commercial") return <CommercialSettings />;
        return <Billing embedded />;
      }}
    </HubLayout>
  );
};
