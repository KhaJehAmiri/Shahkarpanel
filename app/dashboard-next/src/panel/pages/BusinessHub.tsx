import { FC } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useApp } from "../context/AppContext";
import { HubLayout } from "../components/HubLayout";
import { Analytics } from "./Analytics";
import { Automation } from "./Automation";

export const BusinessHub: FC = () => {
  const { t } = useTranslation();
  const { admin } = useApp();
  const [search] = useSearchParams();
  const tab = search.get("tab");

  if (tab === "billing") {
    const billingTab = search.get("billingTab");
    const q = billingTab ? `?billingTab=${encodeURIComponent(billingTab)}` : "";
    return <Navigate to={`/billing${q}`} replace />;
  }
  if (tab === "resellers") return <Navigate to="/resellers" replace />;
  if (tab === "commercial") return <Navigate to="/billing?billingTab=settings" replace />;

  return (
    <HubLayout
      title={t("hub.businessTitle")}
      subtitle={t("hub.businessSubtitle")}
      description={t("hub.businessDesc")}
      defaultTab="analytics"
      tabs={[
        { id: "analytics", label: t("hub.tabAnalytics") },
        { id: "automation", label: t("hub.tabAutomation"), hidden: !admin?.is_sudo },
      ]}
    >
      {(active) => {
        if (active === "automation") return <Automation embedded />;
        return <Analytics embedded />;
      }}
    </HubLayout>
  );
};
