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
import { PanelUpdateWaitingOverlay } from "../components/PanelUpdateWaitingOverlay";
import { WhatsNewModal } from "../components/WhatsNewModal";

const UPDATE_STEP_IDS = ["pull", "backup", "migrate", "build", "restart"] as const;
const VERSION_CACHE_KEY = "nx_panel_version";
const WAIT_KEY = "nx_panel_update_wait";

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

function stashWait(targetVer: string, fromVer: string | null) {
  try {
    sessionStorage.setItem(WAIT_KEY, JSON.stringify({
      targetVer, fromVer, at: Date.now(),
    }));
  } catch { /* ignore */ }
}

function clearWait() {
  try { sessionStorage.removeItem(WAIT_KEY); } catch { /* ignore */ }
}

function readWait(): { targetVer: string; fromVer: string | null } | null {
  try {
    const raw = sessionStorage.getItem(WAIT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { targetVer?: string; fromVer?: string | null; at?: number };
    if (!parsed?.targetVer) return null;
    // Abandon stale waits (>30 min).
    if (parsed.at && Date.now() - parsed.at > 30 * 60 * 1000) {
      clearWait();
      return null;
    }
    return { targetVer: parsed.targetVer, fromVer: parsed.fromVer ?? null };
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
  /** After job success: keep blocking the same panel page until API is back. */
  const [waitingRestart, setWaitingRestart] = useState(false);
  const [waitTarget, setWaitTarget] = useState<string | null>(null);
  const [waitFrom, setWaitFrom] = useState<string | null>(null);
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

  // Resume in-panel wait after a soft remount (same tab still holds the SPA).
  useEffect(() => {
    if (!sudo) return;
    const pending = readWait();
    if (!pending) return;
    setWaitingRestart(true);
    setWaitTarget(pending.targetVer);
    setWaitFrom(pending.fromVer);
    setApplying(true);
  }, [sudo]);

  const hasUpdate = sudo && (
    !!check?.update_available
    || (check?.commits_behind ?? 0) > 0
  );

  const openUpdateModal = useCallback(() => {
    if (!sudo) return;
    setUpdateModalOpen(true);
    // Use cached check first so the modal opens instantly; a background
    // refresh must not race ``git reset`` when the admin hits Apply.
    void refreshCheck(false);
  }, [sudo, refreshCheck]);

  const closeUpdateModal = useCallback(() => {
    if (applying || waitingRestart) return;
    setUpdateModalOpen(false);
  }, [applying, waitingRestart]);

  const finishWaitAndReload = useCallback(async (targetVer: string) => {
    clearWait();
    setWaitingRestart(false);
    setApplying(false);
    setDisplayVersion(targetVer);
    await refreshCheck();
    const bust = encodeURIComponent(targetVer);
    const { pathname, hash } = window.location;
    window.location.replace(`${pathname}?nxv=${bust}${hash}`);
  }, [refreshCheck]);

  const startApply = useCallback(async () => {
    if (!check || applying) return;
    setApplying(true);
    setWaitingRestart(false);
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
          if (j.status === "success" && check) {
            const notes = releaseNotesForLang(check, lang);
            const targetVer = check.remote_version;
            const fromVer = check.current_version;
            stashPendingWhatsNew({ version: targetVer, notes });
            stashWait(targetVer, fromVer);
            setWaitTarget(targetVer);
            setWaitFrom(fromVer);
            setWaitingRestart(true);
            // Keep the panel UI blocked on *this* page — do not close into a bare 502.
            setUpdateModalOpen(false);
          } else {
            setApplying(false);
            setWaitingRestart(false);
            clearWait();
          }
        }
      } catch {
        // API down mid-restart: keep blocking this same panel page.
        if (check?.remote_version) {
          stashWait(check.remote_version, check.current_version);
          setWaitTarget(check.remote_version);
          setWaitFrom(check.current_version);
        }
        setWaitingRestart(true);
      }
    }, 2000);
    return () => clearInterval(id);
  }, [job?.id, job?.finished, check, lang]);

  // Poll until the panel API is back with the target version.
  useEffect(() => {
    if (!waitingRestart || !waitTarget) return;
    let cancelled = false;
    const tick = async () => {
      for (let n = 0; n < 90 && !cancelled; n += 1) {
        try {
          const ver = await fetchInstalledVersion();
          if (ver === waitTarget) {
            await finishWaitAndReload(waitTarget);
            return;
          }
          // Panel is up but still on old version briefly — keep waiting.
        } catch {
          /* still restarting */
        }
        await new Promise((r) => window.setTimeout(r, 2000));
      }
      if (!cancelled) {
        clearWait();
        setWaitingRestart(false);
        setApplying(false);
        window.location.reload();
      }
    };
    void tick();
    return () => { cancelled = true; };
  }, [waitingRestart, waitTarget, finishWaitAndReload]);

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

  const showWaitOverlay = waitingRestart;
  const waitPhase = "restarting" as const;

  return (
    <Ctx.Provider value={value}>
      {children}
      {sudo && (
        <>
          <PanelUpdateModal
            open={updateModalOpen && !waitingRestart}
            check={check}
            checking={checking}
            job={job}
            applying={applying && !waitingRestart}
            onClose={closeUpdateModal}
            onRefresh={() => refreshCheck(true)}
            onApply={startApply}
          />
          <PanelUpdateWaitingOverlay
            open={showWaitOverlay}
            phase={waitPhase}
            fromVersion={waitFrom || check?.current_version}
            toVersion={waitTarget || check?.remote_version}
          />
          {whatsNew && !showWaitOverlay && (
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
