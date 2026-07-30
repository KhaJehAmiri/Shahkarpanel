import { FC } from "react";
import { useTranslation } from "react-i18next";

/** Full-screen blocker on the live panel UI while an update restarts the container. */
export const PanelUpdateWaitingOverlay: FC<{
  open: boolean;
  phase: "installing" | "restarting";
  fromVersion?: string | null;
  toVersion?: string | null;
}> = ({ open, phase, fromVersion, toVersion }) => {
  const { t } = useTranslation();
  if (!open) return null;

  const title = phase === "restarting"
    ? t("system.updateWaitingRestart")
    : t("system.updateJobRunning");
  const hint = phase === "restarting"
    ? t("system.updateWaitingRestartHint")
    : t("system.updateWaitingInstallHint");

  return (
    <div className="sk-update-wait-overlay" role="alertdialog" aria-live="polite" aria-busy="true">
      <div className="sk-update-wait-card">
        <div className="sk-update-wait-brand">Shahkar</div>
        <h2 className="sk-update-wait-title">{title}</h2>
        {(fromVersion || toVersion) && (
          <p className="sk-update-wait-ver">
            {fromVersion ? `v${fromVersion}` : "…"}
            <span aria-hidden> → </span>
            {toVersion ? `v${toVersion}` : "…"}
          </p>
        )}
        <p className="sk-update-wait-hint">{hint}</p>
        <div className="sk-update-wait-spinner" aria-hidden />
      </div>
    </div>
  );
};
