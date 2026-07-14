import { FC } from "react";
import { useTranslation } from "react-i18next";
import { UpdateCheck, UpdateJobInfo } from "../api/types";
import { releaseNotesForLang } from "../lib/releaseNotes";
import { Button, Callout, Modal, Pill } from "./ui";

const STEP_IDS = ["pull", "backup", "migrate", "build", "restart"] as const;

export const PanelUpdateModal: FC<{
  open: boolean;
  check: UpdateCheck | null;
  checking: boolean;
  job: UpdateJobInfo | null;
  applying: boolean;
  onClose: () => void;
  onRefresh: () => void;
  onApply: () => Promise<string | void>;
}> = ({ open, check, checking, job, applying, onClose, onRefresh, onApply }) => {
  const { t, i18n } = useTranslation();
  const hasUpdate = !!check?.update_available || (check?.commits_behind ?? 0) > 0;
  const notes = releaseNotesForLang(check, i18n.language);
  const running = applying || (job && !job.finished);

  const handleApply = async () => {
    if (!check || !hasUpdate) return;
    if (!window.confirm(t("system.updateConfirm", { from: check.current_version, to: check.remote_version }))) return;
    try {
      await onApply();
    } catch {
      /* toast handled by parent if needed */
    }
  };

  return (
    <Modal
      open={open}
      title={t("system.tabUpdates")}
      onClose={running ? () => {} : onClose}
      footer={running ? undefined : (
        <>
          <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="ghost" disabled={checking} onClick={onRefresh}>{t("system.checkUpdates")}</Button>
          {/* Only gate on whether an update exists — a background re-check must
              not disable the button once we already know an update is available. */}
          <Button variant="primary" disabled={!hasUpdate || !!running} onClick={handleApply}>
            {t("system.applyUpdates")}
          </Button>
        </>
      )}
    >
      <div className="nx-update-modal">
        {check ? (
          <div className="nx-update-versions">
            <div>
              <span className="nx-muted">{t("system.updateCurrent")}</span>
              <div className="nx-update-ver">v{check.current_version}</div>
            </div>
            {hasUpdate && (
              <>
                <div className="nx-update-arrow" aria-hidden>→</div>
                <div>
                  <span className="nx-muted">{t("system.updateAvailable")}</span>
                  <div className="nx-update-ver accent">v{check.remote_version}</div>
                </div>
              </>
            )}
          </div>
        ) : checking ? (
          <p className="nx-muted">{t("common.loading")}</p>
        ) : null}

        {check?.breaking && <Callout tone="warn">{t("system.updatesBreaking")}</Callout>}

        {hasUpdate && notes.length > 0 && !running && (
          <div className="nx-whatsnew-notes nx-whatsnew-notes-inline">
            <div className="nx-muted" style={{ fontSize: 12, marginBottom: 8 }}>{t("system.updateReleaseNotes")}</div>
            <ul>
              {notes.map((line) => <li key={line}>{line}</li>)}
            </ul>
          </div>
        )}

        {!hasUpdate && check && !running && (
          <Callout tone="ok">{t("system.updatesUpToDate", { version: check.current_version })}</Callout>
        )}

        {running && job && (
          <div className="nx-update-progress">
            <p className="nx-muted">{t("system.updateJobRunning")}</p>
            <div className="nx-stack" style={{ gap: 8, marginTop: 12 }}>
              {STEP_IDS.map((stepId) => {
                const s = job.steps.find((x) => x.id === stepId);
                const st = s?.status || "pending";
                const tone = st === "done" ? "ok" : st === "failed" ? "danger" : st === "running" ? "accent" : "default";
                return (
                  <div key={stepId} className="nx-row" style={{ gap: 8, fontSize: 13 }}>
                    <Pill tone={tone} dot>{t(`system.updateStep.${stepId}`)}</Pill>
                  </div>
                );
              })}
            </div>
            {job.status === "success" && (
              <Callout tone="ok" className="nx-mt-12">{t("system.updateReloading")}</Callout>
            )}
            {job.error_message && job.status === "failed" && (
              <Callout tone="danger">{job.error_message}</Callout>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
};
