import {
  createContext, FC, ReactNode, useCallback, useContext, useEffect, useMemo, useState,
} from "react";
import { api } from "../api/client";
import { UpdateCheck, UpdateJobInfo } from "../api/types";
import { usePolling } from "../lib/useFetch";
import {
  markReleaseSeen, releaseNotesForLang, stashPendingWhatsNew, consumePendingWhatsNew,
} from "../lib/releaseNotes";
import { PanelUpdateModal } from "../components/PanelUpdateModal";
import { WhatsNewModal } from "../components/WhatsNewModal";

const UPDATE_STEP_IDS = ["pull", "backup", "migrate", "build", "restart"] as const;
const VERSION_CACHE_KEY = "nx_panel_version";

interface UpdateState {
  check: UpdateCheck | null;
  hasUpdate: boolean;
  checking: boolean;
  /** Best-known installed version (sidebar + post-update). */
  displayVersion: string | null;
  refreshCheck: (force?: boolean) => Promise<void>;
  refreshDisplayVersion: () => Promise<string | null>;
  openUpdateModal: () => void;
  closeUpdateModal: () => void;
  updateModalOpen: boolean;
}

const Ctx = createContext<UpdateState>({} as UpdateState);
export const usePanelUpdate = () => useContext(Ctx);

async function fetchInstalledVersion(): Promise<string | null> {
  try {
    const v = await api.get<{ version: string }>(`/system/version?_=${Date.now()}`);
    const ver = v.version?.trim() || null;
    if (ver) sessionStorage.setItem(VERSION_CACHE_KEY, ver);
    return ver;
  } catch {
    return null;
  }
}

export const UpdateProvider: FC<{ sudo: boolean; lang: string; children: ReactNode }> = ({
  sudo, lang, children,
}) => {
  const [check, setCheck] = useState<UpdateCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [displayVersion, setDisplayVersion] = useState<string | null>(() => {
    try {
      return sessionStorage.getItem(VERSION_CACHE_KEY);
    } catch {
      return null;
    }
  });
  const [updateModalOpen, setUpdateModalOpen] = useState(false);
  const [job, setJob] = useState<UpdateJobInfo | null>(null);
  const [applying, setApplying] = useState(false);
  const [whatsNew, setWhatsNew] = useState<{ version: string; notes: string[] } | null>(null);

  const refreshDisplayVersion = useCallback(async () => {
    const ver = await fetchInstalledVersion();
    if (ver) setDisplayVersion(ver);
    return ver;
  }, []);

  const refreshCheck = useCallback(async (force = false) => {
    if (!sudo) return;
    setChecking(true);
    try {
      const res = await api.get<UpdateCheck>(
        `/system/updates/check?_=${Date.now()}${force ? "&force=true" : ""}`,
      );
      setCheck(res);
      if (res.current_version) {
        setDisplayVersion(res.current_version);
        try {
          sessionStorage.setItem(VERSION_CACHE_KEY, res.current_version);
        } catch { /* ignore */ }
      }
    } catch {
      /* keep previous */
    } finally {
      setChecking(false);
    }
  }, [sudo]);

  useEffect(() => {
    if (sudo) {
      void refreshCheck();
      void refreshDisplayVersion();
    }
  }, [sudo, refreshCheck, refreshDisplayVersion]);

  usePolling(() => { refreshCheck(); }, 120000, sudo);

  const hasUpdate = sudo && (
    !!check?.update_available
    || (check?.commits_behind ?? 0) > 0
  );

  const openUpdateModal = useCallback(() => {
    if (!sudo) return;
    setUpdateModalOpen(true);
    refreshCheck();
  }, [sudo, refreshCheck]);

  const closeUpdateModal = useCallback(() => {
    if (applying) return;
    setUpdateModalOpen(false);
  }, [applying]);

  const startApply = useCallback(async () => {
    if (!check || applying) return;
    setApplying(true);
    setJob({ id: "…", status: "running", finished: false, steps: UPDATE_STEP_IDS.map((id) => ({ id, status: "pending" })) });
    try {
      const res = await api.post<{ job_id: string }>("/system/updates/apply");
      setJob({ id: res.job_id, status: "running", finished: false, steps: UPDATE_STEP_IDS.map((id) => ({ id, status: "pending" })) });
      return res.job_id;
    } catch {
      setApplying(false);
      setJob(null);
      throw new Error("apply_failed");
    }
  }, [check, applying]);

  useEffect(() => {
    if (!job || job.finished) return;
    const id = setInterval(async () => {
      try {
        const j = await api.get<UpdateJobInfo>(`/system/updates/jobs/${job.id}`);
        setJob(j);
        if (j.finished) {
          clearInterval(id);
          setApplying(false);
          if (j.status === "success" && check) {
            const notes = releaseNotesForLang(check, lang);
            const targetVer = check.remote_version;
            stashPendingWhatsNew({ version: targetVer, notes });
            setUpdateModalOpen(false);
            const waitForVersion = async () => {
              for (let n = 0; n < 60; n += 1) {
                try {
                  const ver = await fetchInstalledVersion();
                  if (ver === targetVer) {
                    setDisplayVersion(ver);
                    await refreshCheck();
                    const bust = encodeURIComponent(targetVer);
                    const { pathname, hash } = window.location;
                    window.location.replace(`${pathname}?nxv=${bust}${hash}`);
                    return;
                  }
                } catch {
                  /* panel restarting */
                }
                await new Promise((r) => window.setTimeout(r, 2000));
              }
              await refreshCheck();
              window.location.reload();
            };
            void waitForVersion();
          }
        }
      } catch {
        /* panel may restart */
      }
    }, 2000);
    return () => clearInterval(id);
  }, [job?.id, job?.finished, check, lang, refreshCheck]);

  useEffect(() => {
    if (!sudo) return;
    const pending = consumePendingWhatsNew();
    if (pending?.version) setWhatsNew(pending);
  }, [sudo]);

  const value = useMemo(() => ({
    check,
    hasUpdate,
    checking,
    displayVersion,
    refreshCheck,
    refreshDisplayVersion,
    openUpdateModal,
    closeUpdateModal,
    updateModalOpen,
  }), [check, hasUpdate, checking, displayVersion, refreshCheck, refreshDisplayVersion, openUpdateModal, closeUpdateModal, updateModalOpen]);

  return (
    <Ctx.Provider value={value}>
      {children}
      {sudo && (
        <>
          <PanelUpdateModal
            open={updateModalOpen}
            check={check}
            checking={checking}
            job={job}
            applying={applying}
            onClose={closeUpdateModal}
            onRefresh={() => refreshCheck(true)}
            onApply={startApply}
          />
          {whatsNew && (
            <WhatsNewModal
              version={whatsNew.version}
              notes={whatsNew.notes}
              onClose={() => {
                markReleaseSeen(whatsNew.version);
                setWhatsNew(null);
              }}
            />
          )}
        </>
      )}
    </Ctx.Provider>
  );
};
