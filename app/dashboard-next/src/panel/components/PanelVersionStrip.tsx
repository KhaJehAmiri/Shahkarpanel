import { FC, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { SystemStats } from "../api/types";
import { usePanelUpdate } from "../context/UpdateContext";
import { useFetch, useLiveReload, usePolling } from "../lib/useFetch";

/** Sidebar version strip — visible on every dashboard page (sudo: includes update hint). */
export const PanelVersionStrip: FC<{ sudo?: boolean }> = ({ sudo }) => {
  const { t } = useTranslation();
  const {
    hasUpdate, check, openUpdateModal, displayVersion, refreshDisplayVersion,
  } = usePanelUpdate();
  const sys = useFetch<SystemStats>(() => api.get(`/system?_=${Date.now()}`), []);
  useLiveReload(() => {
    sys.reload();
    void refreshDisplayVersion();
  }, 60000);
  usePolling(() => { void refreshDisplayVersion(); }, 15000, sudo);

  useEffect(() => {
    if (check?.current_version) void refreshDisplayVersion();
  }, [check?.current_version, refreshDisplayVersion]);

  const version = displayVersion || check?.current_version || sys.data?.version || "…";
  const remote = check?.remote_version;

  if (sudo && hasUpdate) {
    return (
      <button
        type="button"
        className="nx-side-version nx-side-version-update"
        onClick={openUpdateModal}
      >
        <span className="nx-side-version-label">{t("overview.version")}</span>
        <span className="nx-side-version-val">v{version}</span>
        <span className="nx-side-version-new">
          → v{remote} · {t("system.applyUpdates")}
        </span>
      </button>
    );
  }

  return (
    <div className="nx-side-version">
      <span className="nx-side-version-label">{t("overview.version")}</span>
      <span className="nx-side-version-val">v{version}</span>
    </div>
  );
};
