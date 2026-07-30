import { FC, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { OnboardingStatus } from "../api/types";
import { useApp } from "../context/AppContext";
import { Button, Modal, Pill } from "./ui";

export const ResellerOnboardingWizard: FC = () => {
  const { t } = useTranslation();
  const { admin } = useApp();
  const [status, setStatus] = useState<OnboardingStatus | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!admin || admin.is_sudo) return;
    api.get<OnboardingStatus>("/reseller/onboarding")
      .then(setStatus)
      .catch(() => setStatus(null));
  }, [admin]);

  const finish = async () => {
    setBusy(true);
    try {
      const s = await api.post<OnboardingStatus>("/reseller/onboarding/complete", {});
      setStatus(s);
    } finally {
      setBusy(false);
    }
  };

  if (!status?.show_wizard) return null;

  const steps = status.steps || {};

  return (
    <Modal
      open
      title={t("onboarding.title")}
      onClose={finish}
      footer={
        <>
          <Button variant="ghost" onClick={finish} disabled={busy}>{t("onboarding.skip")}</Button>
          <Button variant="primary" onClick={finish} disabled={busy}>{t("onboarding.done")}</Button>
        </>
      }
    >
      <p className="sk-faint" style={{ fontSize: 13, marginTop: 0 }}>{t("onboarding.description")}</p>
      <div className="sk-stack" style={{ gap: 10 }}>
        <Step done={!!steps.branding} label={t("onboarding.stepBranding")} to="/resellers" />
        <Step done={!!steps.plan} label={t("onboarding.stepPlan")} to="/billing" />
        <Step done={!!steps.user} label={t("onboarding.stepUser")} to="/users" />
      </div>
    </Modal>
  );
};

const Step: FC<{ done: boolean; label: string; to: string }> = ({ done, label, to }) => {
  const { t } = useTranslation();
  return (
    <div className="sk-row" style={{ justifyContent: "space-between", gap: 12 }}>
      <div className="sk-row" style={{ gap: 8 }}>
        <Pill tone={done ? "ok" : "default"} dot>{done ? t("onboarding.doneBadge") : t("onboarding.todoBadge")}</Pill>
        <span>{label}</span>
      </div>
      <Link className="sk-btn sm ghost" to={to}>{t("onboarding.open")}</Link>
    </div>
  );
};
