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

interface UpdateState {
  check: UpdateCheck | null;
  hasUpdate: boolean;
  checking: boolean;
  refreshCheck: () => Promise<void>;
  openUpdateModal: () => void;
  closeUpdateModal: () => void;
  updateModalOpen: boolean;
}

const Ctx = createContext<UpdateState>({} as UpdateState);
export const usePanelUpdate = () => useContext(Ctx);

export const UpdateProvider: FC<{ sudo: boolean; lang: string; children: ReactNode }> = ({
  sudo, lang, children,
}) => {
  const [check, setCheck] = useState<UpdateCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [updateModalOpen, setUpdateModalOpen] = useState(false);
  const [job, setJob] = useState<UpdateJobInfo | null>(null);
  const [applying, setApplying] = useState(false);
  const [whatsNew, setWhatsNew] = useState<{ version: string; notes: string[] } | null>(null);

  const refreshCheck = useCallback(async () => {
    if (!sudo) return;
    setChecking(true);
    try {
      const res = await api.get<UpdateCheck>("/system/updates/check");
      setCheck(res);
    } catch {
      /* keep previous */
    } finally {
      setChecking(false);
    }
  }, [sudo]);

  useEffect(() => {
    if (sudo) refreshCheck();
  }, [sudo, refreshCheck]);

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
              for (let n = 0; n < 45; n += 1) {
                try {
                  const v = await api.get<{ version: string }>("/system/version");
                  if (v.version === targetVer) {
                    window.location.reload();
                    return;
                  }
                } catch {
                  /* panel restarting */
                }
                await new Promise((r) => window.setTimeout(r, 2000));
              }
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
  }, [job?.id, job?.finished, check, lang]);

  useEffect(() => {
    if (!sudo) return;
    const pending = consumePendingWhatsNew();
    if (pending?.version) setWhatsNew(pending);
  }, [sudo]);

  const value = useMemo(() => ({
    check,
    hasUpdate,
    checking,
    refreshCheck,
    openUpdateModal,
    closeUpdateModal,
    updateModalOpen,
  }), [check, hasUpdate, checking, refreshCheck, openUpdateModal, closeUpdateModal, updateModalOpen]);

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
            onRefresh={refreshCheck}
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
