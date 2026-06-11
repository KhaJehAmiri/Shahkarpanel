import { FC } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { SystemStats, UpdateCheck } from "../api/types";
import { useFetch, useLiveReload, usePolling } from "../lib/useFetch";

/** Sidebar version strip — visible on every dashboard page (sudo: includes update hint). */
export const PanelVersionStrip: FC<{ sudo?: boolean }> = ({ sudo }) => {
  const { t } = useTranslation();
  const sys = useFetch<SystemStats>(() => api.get("/system"), []);
  const updates = useFetch<UpdateCheck | null>(
    () => (sudo ? api.get("/system/updates/check") : Promise.resolve(null)),
    [sudo],
  );
  useLiveReload(() => sys.reload(), 60000);
  usePolling(() => updates.reload(), 300000, !!sudo);

  const version = sys.data?.version || "…";
  const hasUpdate = sudo && (updates.data?.commits_behind ?? 0) > 0;
  const remote = updates.data?.remote_version;

  if (sudo && hasUpdate) {
    return (
      <Link to="/system?tab=updates" className="nx-side-version nx-side-version-update">
        <span className="nx-side-version-label">{t("overview.version")}</span>
        <span className="nx-side-version-val">v{version}</span>
        <span className="nx-side-version-new">
          → v{remote} · {t("system.tabUpdates")}
        </span>
      </Link>
    );
  }

  return (
    <div className="nx-side-version">
      <span className="nx-side-version-label">{t("overview.version")}</span>
      <span className="nx-side-version-val">v{version}</span>
    </div>
  );
};
